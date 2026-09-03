from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


class NetworkPolicyError(ValueError):
    """A Skill attempted network access outside its exact host policy."""


_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_PRIVATE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)

_SAFE_CHILD_ENVIRONMENT = (
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PLAYWRIGHT_BROWSERS_PATH",
    # Playwright uses these Windows shell locations to resolve the installed
    # Edge channel. They contain no credentials and are required by browser
    # based Skills after the environment is reduced to this allowlist.
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "WINDIR",
)


@dataclass(frozen=True)
class NetworkTarget:
    scheme: str
    host: str
    port: int

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def normalize_network_policy_mode(value: str | None = None) -> str:
    mode = (value or os.environ.get("FINANCIAL_NETWORK_POLICY_MODE", "strict")).strip().lower()
    if mode not in {"strict", "internal"}:
        raise NetworkPolicyError("网络策略模式只能是 strict 或 internal。")
    return mode


def normalize_allowed_host(value: str) -> str:
    raw = value.strip().rstrip(".").lower()
    if not raw or "*" in raw or "://" in raw or any(char in raw for char in "/?#@:"):
        raise NetworkPolicyError("网络白名单只能包含不带协议、端口和通配符的精确域名。")
    try:
        host = raw.encode("idna").decode("ascii")
        ipaddress.ip_address(host)
    except ValueError:
        pass
    except UnicodeError as exc:
        raise NetworkPolicyError("网络白名单包含无效域名。") from exc
    else:
        raise NetworkPolicyError("网络白名单不能使用 IP 地址，必须配置真实业务域名。")
    if not _HOSTNAME.fullmatch(host):
        raise NetworkPolicyError("网络白名单必须使用完整的精确域名。")
    return host


def _normalize_private_ipv4(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise NetworkPolicyError("内网联调目标必须使用精确私网 IPv4 地址。") from exc
    if not isinstance(address, ipaddress.IPv4Address) or not any(
        address in network for network in _PRIVATE_IPV4_NETWORKS
    ):
        raise NetworkPolicyError("内网联调目标只允许 RFC1918 私网 IPv4 地址。")
    return str(address)


def normalize_network_target(value: str, mode: str | None = None) -> NetworkTarget:
    policy_mode = normalize_network_policy_mode(mode)
    parsed = urlsplit(value.strip())
    if (
        not parsed.scheme
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise NetworkPolicyError("网络目标必须是无路径、无凭据的精确 origin。")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise NetworkPolicyError("网络目标端口无效。") from exc

    scheme = parsed.scheme.lower()
    if scheme == "https":
        host = normalize_allowed_host(parsed.hostname)
        port = explicit_port or 443
        if port != 443:
            raise NetworkPolicyError("正式网络目标只允许 HTTPS 443 端口。")
        return NetworkTarget(scheme="https", host=host, port=port)

    if scheme == "http" and policy_mode == "internal":
        if explicit_port is None:
            raise NetworkPolicyError("内网 HTTP 目标必须显式配置端口。")
        if not 1 <= explicit_port <= 65535:
            raise NetworkPolicyError("内网 HTTP 目标端口无效。")
        host = _normalize_private_ipv4(parsed.hostname)
        return NetworkTarget(scheme="http", host=host, port=explicit_port)

    if scheme == "http":
        raise NetworkPolicyError("strict 模式禁止 HTTP 目标。")
    raise NetworkPolicyError("网络目标协议只能是 HTTPS，内网联调模式可使用 HTTP。")


def normalized_network_targets(runtime: Any) -> tuple[NetworkTarget, ...]:
    values = getattr(runtime, "network_targets", []) or []
    legacy_hosts = getattr(runtime, "network_allowlist", []) or []
    if values and legacy_hosts:
        raise NetworkPolicyError("network_targets 与旧 network_allowlist 不能同时配置。")
    if legacy_hosts:
        values = [f"https://{normalize_allowed_host(str(item))}:443" for item in legacy_hosts]
    targets = tuple(normalize_network_target(str(item)) for item in values)
    origins = tuple(item.origin for item in targets)
    if len(origins) != len(set(origins)):
        raise NetworkPolicyError("网络目标不能重复。")
    return targets


def validate_runtime_network_policy(runtime: Any) -> tuple[str, ...]:
    enabled = bool(getattr(runtime, "network_access", False))
    targets = normalized_network_targets(runtime)
    if enabled and not targets:
        raise NetworkPolicyError("声明网络访问的 Skill 必须配置精确网络目标。")
    if not enabled and targets:
        raise NetworkPolicyError("未启用网络访问时不能配置网络目标。")
    return tuple(item.origin for item in targets)


def normalize_proxy_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise NetworkPolicyError("出站代理必须是无凭据、无路径的内部 HTTP 地址。")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise NetworkPolicyError("出站代理端口无效。") from exc
    if not 1 <= port <= 65535:
        raise NetworkPolicyError("出站代理端口无效。")
    return f"http://{parsed.hostname.lower()}:{port}"


def execution_network_environment(runtime: Any) -> dict[str, str]:
    targets = validate_runtime_network_policy(runtime)
    hosts = tuple(urlsplit(item).hostname or "" for item in targets)
    environment = {
        "FINANCIAL_NETWORK_POLICY_REQUIRED": "1",
        "FINANCIAL_NETWORK_ACCESS": "1" if targets else "0",
        "FINANCIAL_NETWORK_POLICY_MODE": normalize_network_policy_mode(),
        "FINANCIAL_NETWORK_TARGETS": ",".join(targets),
        "FINANCIAL_NETWORK_ALLOWLIST": ",".join(hosts),
    }
    proxy_value = os.environ.get("FINANCIAL_NETWORK_PROXY_URL", "").strip()
    if targets and os.environ.get("FINANCIAL_ENV", "").lower() == "production" and not proxy_value:
        raise NetworkPolicyError("生产环境的联网 Skill 必须通过受控出站代理。")
    if targets and proxy_value:
        proxy_url = normalize_proxy_url(proxy_value)
        environment.update(
            {
                "HTTP_PROXY": proxy_url,
                "HTTPS_PROXY": proxy_url,
                "http_proxy": proxy_url,
                "https_proxy": proxy_url,
            }
        )
    return environment


def subprocess_base_environment() -> dict[str, str]:
    """返回不含平台密钥与数据库连接串的最小子进程环境。"""
    return {key: os.environ[key] for key in _SAFE_CHILD_ENVIRONMENT if os.environ.get(key)}


def skill_subprocess_environment(runtime: Any) -> dict[str, str]:
    """只向受控 Skill 进程传递运行必需变量和声明过的网络能力。"""
    environment = subprocess_base_environment()
    environment.update(execution_network_environment(runtime))
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    return environment


def assert_https_url_allowed(url: str, runtime: Any) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise NetworkPolicyError("生产业务连接必须使用 HTTPS。")
    try:
        port = parsed.port
    except ValueError as exc:
        raise NetworkPolicyError("生产业务连接端口无效。") from exc
    if port not in {None, 443}:
        raise NetworkPolicyError("生产业务连接只允许 HTTPS 443 端口。")
    return assert_url_allowed(url, runtime)


def assert_url_allowed(url: str, runtime: Any) -> str:
    targets = set(validate_runtime_network_policy(runtime))
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NetworkPolicyError("HTTP Skill 只能访问完整的 HTTP 或 HTTPS 地址。")
    if parsed.username or parsed.password:
        raise NetworkPolicyError("网络目标不能在 URL 中携带账号或密码。")
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise NetworkPolicyError("网络目标端口无效。") from exc
    port = explicit_port or (443 if parsed.scheme == "https" else 80)
    origin = f"{parsed.scheme}://{parsed.hostname}:{port}"
    target = normalize_network_target(origin)
    if target.origin not in targets:
        raise NetworkPolicyError(f"网络目标 {target.origin} 不在 Skill 的精确目标白名单中。")
    return target.host
