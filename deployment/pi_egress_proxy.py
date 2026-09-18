"""Agent-only outbound proxy: public destinations plus exact business targets.

Runs on a dedicated Agent network, never the finance database network. Resolves
and validates addresses before connecting to the exact validated IP.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit, urlunsplit

MAX_HEADER = 65536


class Denied(ValueError):
    pass


def private_targets():
    result = set()
    for value in os.environ.get("PI_EGRESS_BUSINESS_TARGETS", "").split(","):
        if not value.strip():
            continue
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid business network target")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Business target must be an origin")
        address = ipaddress.ip_address(parsed.hostname)
        if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
            raise ValueError("Business target must be an explicit private business address")
        result.add((str(address), parsed.port or (443 if parsed.scheme == "https" else 80)))
    return result


async def connect_target(host, port, approved):
    if not host or not 1 <= port <= 65535 or any(x in host for x in "\r\n/@#"):
        raise Denied("Invalid target")
    candidates = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not candidates:
        raise Denied("Unresolved target")
    checked = []
    for family, kind, protocol, _, address in candidates:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global and (str(ip), port) not in approved:
            raise Denied("Private destination not approved")
        checked.append((family, protocol, address[0]))
    last = None
    for family, protocol, address in checked:
        try:
            return await asyncio.open_connection(host=address, port=port, family=family, proto=protocol)
        except OSError as exc:
            last = exc
    raise last or OSError("No target available")


def request_target(header):
    try:
        lines = header.decode("latin1").split("\r\n")
        method, target, version = lines[0].split(" ")
    except ValueError:
        raise Denied("Invalid request") from None
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise Denied("Invalid protocol")
    if method == "CONNECT":
        parsed = urlsplit("//" + target)
        if not parsed.hostname or not parsed.port or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise Denied("Invalid tunnel target")
        return parsed.hostname, parsed.port, None
    parsed = urlsplit(target)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise Denied("Invalid HTTP target")
    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        raise Denied("Unsupported HTTP method")
    port = parsed.port or 80
    headers = []
    counts = {}
    for line in lines[1:]:
        if not line:
            continue
        if line[0].isspace() or ":" not in line:
            raise Denied("Invalid header")
        name, value = line.split(":", 1)
        name = name.lower()
        counts[name] = counts.get(name, 0) + 1
        if name in {"host", "connection", "proxy-connection", "proxy-authorization"}:
            continue
        headers.append(line)
    if counts.get("content-length", 0) > 1 or counts.get("transfer-encoding", 0) > 1:
        raise Denied("Ambiguous body framing")
    if counts.get("content-length") and counts.get("transfer-encoding"):
        raise Denied("Ambiguous body framing")
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    host_header = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    authority = host_header if port == 80 else f"{host_header}:{port}"
    forward = "\r\n".join([f"{method} {path} {version}", f"Host: {authority}", *headers,
                               "Connection: close", "", ""]).encode("latin1")
    return parsed.hostname, port, forward


async def relay(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (OSError, ConnectionError):
        pass
    finally:
        try:
            writer.write_eof()
        except (OSError, AttributeError, RuntimeError):
            pass


async def client(reader, writer, approved):
    remote = None
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
        if len(header) > MAX_HEADER:
            raise Denied("Header too large")
        host, port, forwarded = request_target(header)
        if host == 'platform-model.internal':
            if port != 80 or (forwarded is not None and not forwarded.startswith(b'POST /v1/chat/completions HTTP/')):
                raise Denied('Unsupported model operation')
            upstream, remote = await asyncio.wait_for(asyncio.open_unix_connection(
                os.environ.get('PI_MODEL_SOCKET', '/model-socket/model.sock')), 20)
        else:
            upstream, remote = await asyncio.wait_for(connect_target(host, port, approved), 20)
        if forwarded is None:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            remote.write(forwarded)
            await remote.drain()
        upload = asyncio.create_task(relay(reader, remote))
        download = asyncio.create_task(relay(upstream, writer))
        try:
            await download
        finally:
            upload.cancel()
            await asyncio.gather(upload, return_exceptions=True)
    except (Denied, ValueError):
        writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, OSError):
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
    finally:
        if remote:
            remote.close()
        try:
            await writer.drain()
        except OSError:
            pass
        writer.close()


async def main():
    approved = private_targets()
    server = await asyncio.start_server(lambda r, w: client(r, w, approved),
                                        "0.0.0.0", int(os.environ.get("PORT", "8080")), limit=MAX_HEADER)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
