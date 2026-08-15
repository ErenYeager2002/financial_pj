from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from scripts import prepare_production_env as production_env

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_normalize_public_origin_accepts_https_fqdn_and_localhost() -> None:
    assert production_env.normalize_public_origin("https://finance.example.com/") == (
        "https://finance.example.com",
        "finance.example.com",
    )
    assert production_env.normalize_public_origin("https://localhost:8443") == (
        "https://localhost:8443",
        "localhost",
    )


@pytest.mark.parametrize(
    "value",
    [
        "http://finance.example.com",
        "https://192.168.10.10",
        "https://finance.example.com/path",
        "https://user:secret@finance.example.com",
    ],
)
def test_normalize_public_origin_rejects_insecure_or_non_domain_values(value: str) -> None:
    with pytest.raises(RuntimeError):
        production_env.normalize_public_origin(value)


def test_zhiyun_url_must_be_https_443_and_in_exact_allowlist() -> None:
    targets = ("https://zhiyun.finance.example.com:443",)
    assert production_env.normalize_zhiyun_base_url(
        "https://zhiyun.finance.example.com",
        targets,
        "strict",
    ) == "https://zhiyun.finance.example.com:443"
    with pytest.raises(RuntimeError, match="出站目标"):
        production_env.normalize_zhiyun_base_url(
            "https://other.example.com",
            targets,
            "strict",
        )
    with pytest.raises(RuntimeError, match="HTTP"):
        production_env.normalize_zhiyun_base_url(
            "http://zhiyun.finance.example.com",
            targets,
            "strict",
        )
    with pytest.raises(RuntimeError, match="443"):
        production_env.normalize_zhiyun_base_url(
            "https://zhiyun.finance.example.com:8443",
            targets,
            "strict",
        )


def test_internal_zhiyun_url_requires_exact_private_target() -> None:
    targets = ("http://192.168.10.167:18880",)
    assert production_env.normalize_zhiyun_base_url(
        "http://192.168.10.167:18880",
        targets,
        "internal",
    ) == "http://192.168.10.167:18880"
    with pytest.raises(RuntimeError, match="出站目标"):
        production_env.normalize_zhiyun_base_url(
            "http://192.168.10.168:18880",
            targets,
            "internal",
        )


def test_validate_production_values_accepts_deny_all_local_config(tmp_path: Path) -> None:
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("https://localhost {}", encoding="utf-8")
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    values = {
        "POSTGRES_PASSWORD": "not-printed",
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": "pk_test_placeholder",
        "CLERK_SECRET_KEY": "sk_test_placeholder",
        "FINANCIAL_CLERK_ISSUER": "https://issuer.example.com",
        "PLATFORM_PUBLIC_ORIGIN": "https://localhost:8443",
        "PLATFORM_HOST": "localhost",
        "PLATFORM_BIND_ADDRESS": "127.0.0.1",
        "PLATFORM_HTTPS_PORT": "8443",
        "CADDYFILE_PATH": str(caddyfile),
        "PLATFORM_TLS_DIR": str(tls_dir),
        "FINANCIAL_CLERK_AUTHORIZED_PARTIES": "https://localhost:8443",
        "FINANCIAL_TRUSTED_ORIGINS": "https://localhost:8443",
        "FINANCIAL_NETWORK_POLICY_MODE": "strict",
        "FINANCIAL_EGRESS_PROXY_TARGETS": "",
        "FINANCIAL_EGRESS_PROXY_ALLOWLIST": "",
        "FINANCIAL_ZHIYUN_BASE_URL": "",
    }
    production_env.validate_production_values(values)


def test_internal_mode_requires_loopback_platform_listener(tmp_path: Path) -> None:
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text("https://localhost {}", encoding="utf-8")
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    values = {
        "POSTGRES_PASSWORD": "not-printed",
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": "pk_test_placeholder",
        "CLERK_SECRET_KEY": "sk_test_placeholder",
        "FINANCIAL_CLERK_ISSUER": "https://issuer.example.com",
        "PLATFORM_PUBLIC_ORIGIN": "https://localhost:8443",
        "PLATFORM_HOST": "localhost",
        "PLATFORM_BIND_ADDRESS": "0.0.0.0",
        "PLATFORM_HTTPS_PORT": "8443",
        "CADDYFILE_PATH": str(caddyfile),
        "PLATFORM_TLS_DIR": str(tls_dir),
        "FINANCIAL_CLERK_AUTHORIZED_PARTIES": "https://localhost:8443",
        "FINANCIAL_TRUSTED_ORIGINS": "https://localhost:8443",
        "FINANCIAL_NETWORK_POLICY_MODE": "internal",
        "FINANCIAL_EGRESS_PROXY_TARGETS": "http://192.168.10.167:18880",
        "FINANCIAL_EGRESS_PROXY_ALLOWLIST": "",
        "FINANCIAL_ZHIYUN_BASE_URL": "http://192.168.10.167:18880",
    }
    with pytest.raises(RuntimeError, match="回环"):
        production_env.validate_production_values(values)


def test_production_compose_uses_shared_runtime_skill_volume() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "deploy" / "production" / "compose.yaml").read_text(
            encoding="utf-8"
        )
    )
    services = compose["services"]
    assert "skill-data:/app/skills" in services["api"]["volumes"]
    for pool in ("python", "http", "workflow"):
        for index in (1, 2):
            service = services[f"worker-{pool}-{index}"]
            assert "skill-data:/app/skills:ro" in service["volumes"]
    assert "skill-data" in compose["volumes"]
