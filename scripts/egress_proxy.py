from __future__ import annotations

import argparse
import asyncio
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.network_policy import (
    NetworkPolicyError,
    NetworkTarget,
    normalize_allowed_host,
    normalize_network_policy_mode,
    normalize_network_target,
)

MAX_HEADER_BYTES = 64 * 1024


class ProxyRequestError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ProxyPolicy:
    targets: frozenset[NetworkTarget]

    @classmethod
    def from_environment(cls) -> ProxyPolicy:
        raw_targets = [
            item.strip()
            for item in os.environ.get("FINANCIAL_EGRESS_PROXY_TARGETS", "").split(",")
            if item.strip()
        ]
        if not raw_targets:
            raw_hosts = [
                item.strip()
                for item in os.environ.get("FINANCIAL_EGRESS_PROXY_ALLOWLIST", "").split(",")
                if item.strip()
            ]
            raw_targets = [f"https://{normalize_allowed_host(item)}:443" for item in raw_hosts]
        targets = [normalize_network_target(item) for item in raw_targets]
        if len(targets) != len(set(targets)):
            raise NetworkPolicyError("出站代理不能包含重复目标。")
        return cls(targets=frozenset(targets))

    def authorize_connect(self, target: str) -> tuple[str, int]:
        host, separator, raw_port = target.rpartition(":")
        if not separator or not host or not raw_port or "[" in host or "]" in host:
            raise ProxyRequestError(400, "CONNECT 目标格式无效。")
        try:
            port = int(raw_port)
            normalized = normalize_network_target(f"https://{host}:{port}")
        except (NetworkPolicyError, ValueError) as exc:
            raise ProxyRequestError(403, "CONNECT 目标未获批准。") from exc
        if normalized not in self.targets:
            raise ProxyRequestError(403, "CONNECT 目标未获批准。")
        return normalized.host, normalized.port

    def authorize_http(self, url: str) -> NetworkTarget:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "http" or not parsed.hostname:
            raise ProxyRequestError(403, "HTTP 目标未获批准。")
        try:
            port = parsed.port or 80
            normalized = normalize_network_target(f"http://{parsed.hostname}:{port}")
        except (NetworkPolicyError, ValueError) as exc:
            raise ProxyRequestError(403, "HTTP 目标未获批准。") from exc
        if normalized not in self.targets:
            raise ProxyRequestError(403, "HTTP 目标未获批准。")
        return normalized


def parse_connect_request(header: bytes, policy: ProxyPolicy) -> tuple[str, int]:
    try:
        first_line = header.split(b"\r\n", 1)[0].decode("ascii")
        method, target, version = first_line.split(" ", 2)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProxyRequestError(400, "代理请求格式无效。") from exc
    if method.upper() != "CONNECT":
        raise ProxyRequestError(405, "出站代理只允许 HTTPS CONNECT。")
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ProxyRequestError(400, "代理请求协议无效。")
    return policy.authorize_connect(target)


def prepare_http_request(header: bytes, policy: ProxyPolicy) -> tuple[str, int, bytes]:
    try:
        lines = header.split(b"\r\n")
        method, absolute_url, version = lines[0].decode("ascii").split(" ", 2)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProxyRequestError(400, "代理请求格式无效。") from exc
    method = method.upper()
    if method not in {"GET", "HEAD", "POST", "OPTIONS"}:
        raise ProxyRequestError(405, "内网取数代理只允许读取和登录所需的 HTTP 方法。")
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ProxyRequestError(400, "代理请求协议无效。")
    target = policy.authorize_http(absolute_url)
    parsed = urlsplit(absolute_url)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))

    forwarded_headers: list[bytes] = []
    for raw_line in lines[1:]:
        if not raw_line:
            continue
        if raw_line[:1] in {b" ", b"\t"} or b":" not in raw_line:
            raise ProxyRequestError(400, "代理请求头格式无效。")
        name = raw_line.split(b":", 1)[0].strip().lower()
        if name in {b"connection", b"host", b"proxy-authorization", b"proxy-connection"}:
            continue
        forwarded_headers.append(raw_line)
    host_header = target.host if target.port == 80 else f"{target.host}:{target.port}"
    request_lines = [
        f"{method} {path} {version}".encode("ascii"),
        f"Host: {host_header}".encode("ascii"),
        *forwarded_headers,
        b"Connection: close",
        b"",
        b"",
    ]
    return target.host, target.port, b"\r\n".join(request_lines)


async def _open_exact_target(
    host: str,
    port: int,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    loop = asyncio.get_running_loop()
    candidates = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    last_error: OSError | None = None
    for family, _socket_type, protocol, _canonical, address in candidates:
        try:
            return await asyncio.open_connection(
                host=address[0],
                port=address[1],
                family=family,
                proto=protocol,
            )
        except OSError as exc:
            last_error = exc
    raise last_error or OSError("批准域名没有可连接的地址。")


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(64 * 1024):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.write_eof()
        except (AttributeError, OSError, RuntimeError):
            pass


async def _relay_both_directions(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    remote_reader: asyncio.StreamReader,
    remote_writer: asyncio.StreamWriter,
) -> None:
    tasks = {
        asyncio.create_task(_relay(client_reader, remote_writer)),
        asyncio.create_task(_relay(remote_reader, client_writer)),
    }
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _relay_http_response(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    remote_reader: asyncio.StreamReader,
    remote_writer: asyncio.StreamWriter,
) -> None:
    upload = asyncio.create_task(_relay(client_reader, remote_writer))
    download = asyncio.create_task(_relay(remote_reader, client_writer))
    await download
    if not upload.done():
        upload.cancel()
    await asyncio.gather(upload, return_exceptions=True)


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    policy: ProxyPolicy,
) -> None:
    remote_writer: asyncio.StreamWriter | None = None
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        if len(header) > MAX_HEADER_BYTES:
            raise ProxyRequestError(431, "代理请求头过大。")
        method = header.split(b" ", 1)[0].upper()
        if method == b"CONNECT":
            host, port = parse_connect_request(header, policy)
            upstream_header = None
        else:
            host, port, upstream_header = prepare_http_request(header, policy)
        remote_reader, remote_writer = await asyncio.wait_for(
            _open_exact_target(host, port),
            timeout=15,
        )
        if upstream_header is None:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            remote_writer.write(upstream_header)
            await remote_writer.drain()
        if upstream_header is None:
            await _relay_both_directions(reader, writer, remote_reader, remote_writer)
        else:
            # An HTTP client may half-close its upload side after sending the request.
            # Keep receiving the upstream response until the server closes it.
            await _relay_http_response(reader, writer, remote_reader, remote_writer)
    except asyncio.IncompleteReadError:
        pass
    except asyncio.LimitOverrunError:
        writer.write(b"HTTP/1.1 431 Request Header Fields Too Large\r\nConnection: close\r\n\r\n")
        await writer.drain()
    except ProxyRequestError as exc:
        response = f"HTTP/1.1 {exc.status} Denied\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        writer.write(response.encode("ascii"))
        await writer.drain()
    except (TimeoutError, OSError):
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
    finally:
        if remote_writer is not None:
            remote_writer.close()
            try:
                await remote_writer.wait_closed()
            except (ConnectionError, OSError):
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def serve(host: str, port: int, policy: ProxyPolicy) -> None:
    server = await asyncio.start_server(
        lambda reader, writer: handle_client(reader, writer, policy),
        host,
        port,
        limit=MAX_HEADER_BYTES,
    )
    mode = normalize_network_policy_mode()
    target_count = len(policy.targets)
    print(
        f"Financial egress proxy started; mode={mode}; allowed_targets={target_count}",
        flush=True,
    )
    async with server:
        await server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="财务平台精确域名 HTTPS 出站代理")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    policy = ProxyPolicy.from_environment()
    if args.check:
        print(f"配置有效；允许目标数量={len(policy.targets)}")
        return 0
    asyncio.run(serve(args.host, args.port, policy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
