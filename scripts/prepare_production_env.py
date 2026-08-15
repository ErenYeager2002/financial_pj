from __future__ import annotations

import argparse
import ipaddress
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.network_policy import (  # noqa: E402
    NetworkPolicyError,
    normalize_allowed_host,
    normalize_network_policy_mode,
    normalize_network_target,
)


def default_next_root(project_root: Path = PROJECT_ROOT) -> Path:
    return project_root / "web"


NEXT_ROOT = Path(os.getenv("NEXT_APP_DIR", str(default_next_root())))
OUTPUT = PROJECT_ROOT / "deploy" / "production" / ".env"
LOCAL_CADDYFILE = PROJECT_ROOT / "deploy" / "production" / "Caddyfile"
LOCAL_TLS_DIR = PROJECT_ROOT / "deploy" / "production" / "tls"


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        result[key.strip()] = value
    return result


def require(values: dict[str, str], key: str, source: Path) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{source} 缺少 {key}。")
    return value


def normalize_public_origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("平台正式地址必须是无路径、无凭据的 HTTPS origin。")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("平台 HTTPS 端口无效。") from exc
    raw_host = parsed.hostname.lower().rstrip(".")
    if raw_host == "localhost":
        host = raw_host
    else:
        try:
            host = normalize_allowed_host(raw_host)
        except NetworkPolicyError as exc:
            raise RuntimeError(str(exc)) from exc
    netloc = host if port is None else f"{host}:{port}"
    return f"https://{netloc}", host


def normalize_bind_address(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise RuntimeError("监听地址必须是有效 IPv4 或 IPv6 地址。") from exc


def normalize_port(value: str | int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("HTTPS 监听端口无效。") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("HTTPS 监听端口必须位于 1 到 65535。")
    return port


def resolve_existing_path(value: str, label: str, *, directory: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        expected = "目录" if directory else "文件"
        raise RuntimeError(f"{label}{expected}不存在：{path}")
    return path


def normalize_egress_targets(values: list[str], mode: str) -> tuple[str, ...]:
    try:
        targets = tuple(
            normalize_network_target(item, mode).origin for item in values if item.strip()
        )
    except NetworkPolicyError as exc:
        raise RuntimeError(str(exc)) from exc
    if len(targets) != len(set(targets)):
        raise RuntimeError("出站代理不能包含重复目标。")
    return targets


def normalize_zhiyun_base_url(value: str, egress_targets: tuple[str, ...], mode: str) -> str:
    if not value.strip():
        return ""
    try:
        target = normalize_network_target(value, mode)
    except NetworkPolicyError as exc:
        raise RuntimeError(str(exc)) from exc
    if target.origin not in egress_targets:
        raise RuntimeError("智云地址必须同时出现在精确出站目标中。")
    return target.origin


def validate_production_values(values: dict[str, str]) -> None:
    origin, host = normalize_public_origin(require(values, "PLATFORM_PUBLIC_ORIGIN", OUTPUT))
    if values.get("PLATFORM_HOST") != host:
        raise RuntimeError("PLATFORM_HOST 必须与 PLATFORM_PUBLIC_ORIGIN 的域名一致。")
    if values.get("FINANCIAL_CLERK_AUTHORIZED_PARTIES") != origin:
        raise RuntimeError("Clerk authorized party 必须与平台 HTTPS origin 完全一致。")
    if values.get("FINANCIAL_TRUSTED_ORIGINS") != origin:
        raise RuntimeError("可信来源必须与平台 HTTPS origin 完全一致。")
    bind_address = normalize_bind_address(require(values, "PLATFORM_BIND_ADDRESS", OUTPUT))
    normalize_port(require(values, "PLATFORM_HTTPS_PORT", OUTPUT))
    resolve_existing_path(require(values, "CADDYFILE_PATH", OUTPUT), "Caddy 配置")
    resolve_existing_path(require(values, "PLATFORM_TLS_DIR", OUTPUT), "TLS ", directory=True)
    try:
        mode = normalize_network_policy_mode(values.get("FINANCIAL_NETWORK_POLICY_MODE"))
    except NetworkPolicyError as exc:
        raise RuntimeError(str(exc)) from exc
    if mode == "internal" and not ipaddress.ip_address(bind_address).is_loopback:
        raise RuntimeError("内网联调模式下平台入口必须保持回环监听。")
    raw_targets = values.get("FINANCIAL_EGRESS_PROXY_TARGETS", "").split(",")
    if not any(item.strip() for item in raw_targets):
        raw_targets = [
            f"https://{normalize_allowed_host(item)}:443"
            for item in values.get("FINANCIAL_EGRESS_PROXY_ALLOWLIST", "").split(",")
            if item.strip()
        ]
    targets = normalize_egress_targets(raw_targets, mode)
    normalize_zhiyun_base_url(
        values.get("FINANCIAL_ZHIYUN_BASE_URL", ""),
        targets,
        mode,
    )
    for key in (
        "POSTGRES_PASSWORD",
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        "CLERK_SECRET_KEY",
        "FINANCIAL_CLERK_ISSUER",
    ):
        require(values, key, OUTPUT)


def restrict_acl(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return
    username = os.environ.get("USERNAME", "")
    commands = [
        ["icacls", str(path), "/inheritance:r"],
        [
            "icacls",
            str(path),
            "/grant:r",
            f"{username}:(R,W)",
            "*S-1-5-18:(F)",
            "*S-1-5-32-544:(F)",
        ],
    ]
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            raise RuntimeError("无法限制生产环境配置文件 ACL。")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成并校验财务平台生产环境配置")
    parser.add_argument("--public-origin", help="平台 HTTPS origin，例如 https://finance.example.com")
    parser.add_argument("--bind-address", help="网关监听地址；本机试用默认 127.0.0.1")
    parser.add_argument("--https-port", type=int, help="主机 HTTPS 端口")
    parser.add_argument("--caddyfile", help="Caddy 配置文件路径")
    parser.add_argument("--tls-dir", help="只读挂载到 Caddy 的证书目录")
    parser.add_argument("--egress-host", action="append", help="允许出站的精确 FQDN，可重复")
    parser.add_argument(
        "--network-mode",
        choices=("strict", "internal"),
        help="strict 仅允许 HTTPS FQDN；internal 允许精确私网 IPv4 和 HTTP 端口",
    )
    parser.add_argument("--egress-target", action="append", help="允许出站的精确 origin，可重复")
    parser.add_argument("--zhiyun-base-url", help="智云精确 origin")
    parser.add_argument("--check", action="store_true", help="只校验现有生产配置")
    return parser


def build_values(args: argparse.Namespace) -> dict[str, str]:
    next_env_path = NEXT_ROOT / ".env.local"
    backend_env_path = PROJECT_ROOT / ".env.runtime.local"
    next_env = read_env(next_env_path)
    backend_env = read_env(backend_env_path)
    existing = read_env(OUTPUT)

    origin, host = normalize_public_origin(
        args.public_origin
        or existing.get("PLATFORM_PUBLIC_ORIGIN")
        or "https://localhost:8443"
    )
    bind_address = normalize_bind_address(
        args.bind_address or existing.get("PLATFORM_BIND_ADDRESS") or "127.0.0.1"
    )
    https_port = normalize_port(
        args.https_port or existing.get("PLATFORM_HTTPS_PORT") or 8443
    )
    caddyfile = resolve_existing_path(
        args.caddyfile or existing.get("CADDYFILE_PATH") or str(LOCAL_CADDYFILE),
        "Caddy 配置",
    )
    tls_dir = resolve_existing_path(
        args.tls_dir or existing.get("PLATFORM_TLS_DIR") or str(LOCAL_TLS_DIR),
        "TLS ",
        directory=True,
    )
    try:
        network_mode = normalize_network_policy_mode(
            args.network_mode or existing.get("FINANCIAL_NETWORK_POLICY_MODE") or "strict"
        )
    except NetworkPolicyError as exc:
        raise RuntimeError(str(exc)) from exc
    if args.egress_target is not None and args.egress_host is not None:
        raise RuntimeError("--egress-target 与 --egress-host 不能同时使用。")
    if args.egress_target is not None:
        raw_targets = args.egress_target
    elif args.egress_host is not None:
        raw_targets = [f"https://{normalize_allowed_host(item)}:443" for item in args.egress_host]
    else:
        raw_targets = existing.get("FINANCIAL_EGRESS_PROXY_TARGETS", "").split(",")
        if not any(item.strip() for item in raw_targets):
            raw_targets = [
                f"https://{normalize_allowed_host(item)}:443"
                for item in existing.get("FINANCIAL_EGRESS_PROXY_ALLOWLIST", "").split(",")
                if item.strip()
            ]
    egress_targets = normalize_egress_targets(raw_targets, network_mode)
    zhiyun_base_url = normalize_zhiyun_base_url(
        args.zhiyun_base_url
        if args.zhiyun_base_url is not None
        else existing.get("FINANCIAL_ZHIYUN_BASE_URL", ""),
        egress_targets,
        network_mode,
    )
    values = {
        "FINANCIAL_PLATFORM_DIR": PROJECT_ROOT.as_posix(),
        "NEXT_APP_DIR": NEXT_ROOT.resolve().as_posix(),
        "FINANCIAL_DATA_DIR": (PROJECT_ROOT / "data").resolve().as_posix(),
        "POSTGRES_PASSWORD": existing.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(36),
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": require(
            next_env, "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", next_env_path
        ),
        "CLERK_SECRET_KEY": require(next_env, "CLERK_SECRET_KEY", next_env_path),
        "FINANCIAL_AUTH_MODE": "clerk",
        "FINANCIAL_CLERK_ISSUER": require(
            backend_env, "FINANCIAL_CLERK_ISSUER", backend_env_path
        ),
        "FINANCIAL_CLERK_AUTHORIZED_PARTIES": origin,
        "FINANCIAL_TRUSTED_ORIGINS": origin,
        "PLATFORM_PUBLIC_ORIGIN": origin,
        "PLATFORM_HOST": host,
        "PLATFORM_BIND_ADDRESS": bind_address,
        "PLATFORM_HTTPS_PORT": str(https_port),
        "CADDYFILE_PATH": caddyfile.as_posix(),
        "PLATFORM_TLS_DIR": tls_dir.as_posix(),
        "FINANCIAL_NETWORK_POLICY_MODE": network_mode,
        "FINANCIAL_EGRESS_PROXY_TARGETS": ",".join(egress_targets),
        "FINANCIAL_EGRESS_PROXY_ALLOWLIST": ",".join(
            urlsplit(item).hostname or ""
            for item in egress_targets
            if item.startswith("https://")
        ),
        "FINANCIAL_ZHIYUN_BASE_URL": zhiyun_base_url,
    }
    validate_production_values(values)
    return values


def main() -> int:
    args = _parser().parse_args()
    if args.check:
        validate_production_values(read_env(OUTPUT))
        print("生产环境配置校验通过；未输出任何密钥或密码值。")
        return 0

    values = build_values(args)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    restrict_acl(OUTPUT)
    print(f"生产环境配置已生成并限制 ACL：{OUTPUT}")
    print("已写入配置项名称；未输出任何密钥或密码值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
