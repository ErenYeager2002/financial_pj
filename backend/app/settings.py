from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(
    os.getenv("FINANCIAL_PROJECT_ROOT", Path(__file__).resolve().parents[2])
).resolve()


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


def _worker_counts() -> tuple[tuple[str, int], ...]:
    raw = os.getenv("FINANCIAL_WORKER_COUNTS", "python:2,http:2,workflow:2")
    counts: list[tuple[str, int]] = []
    for item in raw.split(","):
        pool, separator, count = item.strip().partition(":")
        if not separator or not pool.strip():
            continue
        try:
            parsed = int(count.strip())
        except ValueError:
            continue
        if parsed > 0:
            counts.append((pool.strip(), parsed))
    return tuple(counts) or (("python", 2), ("http", 2), ("workflow", 2))


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("FINANCIAL_APP_NAME", "财务 Skill 运行平台")
    environment: str = os.getenv("FINANCIAL_ENV", "development")
    project_root: Path = PROJECT_ROOT
    data_dir: Path = _env_path("FINANCIAL_DATA_DIR", PROJECT_ROOT / "data")
    skill_dir: Path = _env_path("FINANCIAL_SKILL_DIR", PROJECT_ROOT / "skills")
    external_skill_dir: Path | None = (
        _env_path("FINANCIAL_EXTERNAL_SKILL_DIR", PROJECT_ROOT)
        if os.getenv("FINANCIAL_EXTERNAL_SKILL_DIR")
        else None
    )
    database_url: str = os.getenv(
        "FINANCIAL_DATABASE_URL",
        f"sqlite:///{(PROJECT_ROOT / 'data' / 'financial.db').as_posix()}",
    )
    max_upload_mb: int = int(os.getenv("FINANCIAL_MAX_UPLOAD_MB", "100"))
    file_retention_days: int = max(1, int(os.getenv("FINANCIAL_FILE_RETENTION_DAYS", "90")))
    fetch_bundle_retention_days: int = max(
        0,
        int(os.getenv("FINANCIAL_FETCH_BUNDLE_RETENTION_DAYS", "0")),
    )
    task_draft_ttl_minutes: int = max(5, int(os.getenv("FINANCIAL_TASK_DRAFT_TTL_MINUTES", "30")))
    approval_ttl_minutes: int = max(5, int(os.getenv("FINANCIAL_APPROVAL_TTL_MINUTES", "30")))
    queue_poll_seconds: float = float(os.getenv("FINANCIAL_QUEUE_POLL_SECONDS", "1"))
    worker_pools: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("FINANCIAL_WORKER_POOLS", "python,http,workflow").split(",")
        if item.strip()
    )
    worker_counts: tuple[tuple[str, int], ...] = _worker_counts()
    worker_lease_seconds: int = max(15, int(os.getenv("FINANCIAL_WORKER_LEASE_SECONDS", "60")))
    worker_heartbeat_seconds: int = max(
        5, int(os.getenv("FINANCIAL_WORKER_HEARTBEAT_SECONDS", "15"))
    )
    worker_max_attempts: int = max(1, int(os.getenv("FINANCIAL_WORKER_MAX_ATTEMPTS", "2")))
    llm_base_url: str = os.getenv("FINANCIAL_LLM_BASE_URL", "").rstrip("/")
    llm_api_key: str = os.getenv("FINANCIAL_LLM_API_KEY", "")
    llm_model: str = os.getenv("FINANCIAL_LLM_MODEL", "")
    llm_provider: str = os.getenv("FINANCIAL_LLM_PROVIDER", "")
    zhiyun_base_url: str = os.getenv("FINANCIAL_ZHIYUN_BASE_URL", "").rstrip("/")
    # Read-only reminder discovery is independently gated from reconciliation.
    task_discovery_enabled: bool = _env_bool(
        "FINANCIAL_TASK_DISCOVERY_ENABLED",
        False,
    )
    task_discovery_holidays: tuple[str, ...] = _csv_env("FINANCIAL_TASK_DISCOVERY_HOLIDAYS")
    # AR reconciliation stays available to synthetic tests only until the
    # production read-only gate is explicitly lifted.
    ar_hexiao_execution_enabled: bool = _env_bool(
        "FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED",
        os.getenv("FINANCIAL_ENV", "development").strip().lower() == "test",
    )
    # Existing Zhiyun snapshots may be replayed only by development/test
    # deployments.  This is deliberately separate from the live execution
    # gate: turning live execution on must never be a prerequisite for an
    # offline replay.
    ar_hexiao_snapshot_replay_enabled: bool = _env_bool(
        "FINANCIAL_AR_HEXIAO_SNAPSHOT_REPLAY_ENABLED",
        os.getenv("FINANCIAL_ENV", "development").strip().lower() in {"development", "test"},
    )

    # 会话与认证
    session_cookie_name: str = os.getenv("FINANCIAL_SESSION_COOKIE", "financial_session")
    session_max_age_seconds: int = int(os.getenv("FINANCIAL_SESSION_MAX_AGE_SECONDS", "28800"))
    session_cookie_secure: bool = os.getenv("FINANCIAL_SESSION_COOKIE_SECURE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    session_cookie_samesite: str = os.getenv("FINANCIAL_SESSION_COOKIE_SAMESITE", "lax")
    login_failure_limit: int = max(1, int(os.getenv("FINANCIAL_LOGIN_FAILURE_LIMIT", "5")))
    login_lockout_seconds: int = max(1, int(os.getenv("FINANCIAL_LOGIN_LOCKOUT_SECONDS", "300")))
    bootstrap_admin_username: str = os.getenv("FINANCIAL_BOOTSTRAP_ADMIN_USERNAME", "admin")
    bootstrap_admin_password: str = os.getenv("FINANCIAL_BOOTSTRAP_ADMIN_PASSWORD", "")
    auth_mode: str = os.getenv("FINANCIAL_AUTH_MODE", "session").strip().lower()
    clerk_issuer: str = os.getenv("FINANCIAL_CLERK_ISSUER", "").rstrip("/")
    clerk_jwks_url: str = os.getenv("FINANCIAL_CLERK_JWKS_URL", "")
    clerk_jwt_key: str = os.getenv("FINANCIAL_CLERK_JWT_KEY", "").replace("\\n", "\n")
    clerk_audience: str = os.getenv("FINANCIAL_CLERK_AUDIENCE", "")
    clerk_authorized_parties: tuple[str, ...] = _csv_env("FINANCIAL_CLERK_AUTHORIZED_PARTIES")
    clerk_jwt_leeway_seconds: int = max(
        0, int(os.getenv("FINANCIAL_CLERK_JWT_LEEWAY_SECONDS", "5"))
    )
    dev_clerk_auto_provision_admin: bool = _env_bool(
        "FINANCIAL_DEV_CLERK_AUTO_PROVISION_ADMIN",
        False,
    )

    @property
    def trusted_origins(self) -> tuple[str, ...]:
        """显式可信来源（逗号分隔）。默认从请求 Host 推导同源。"""
        raw = os.getenv("FINANCIAL_TRUSTED_ORIGINS", "")
        return tuple(item.strip() for item in raw.split(",") if item.strip())

    @property
    def custom_llm_host_allowlist(self) -> tuple[str, ...]:
        """自定义模型服务允许的主机名白名单（逗号分隔的精确主机名，默认空）。"""
        raw = os.getenv("FINANCIAL_LLM_CUSTOM_HOST_ALLOWLIST", "")
        return tuple(item.strip().lower() for item in raw.split(",") if item.strip())

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def workflow_dir(self) -> Path:
        return self.data_dir / "workflows"

    @property
    def avatar_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def skill_release_dir(self) -> Path:
        return self.data_dir / "skill-releases"

    @property
    def skill_release_inbox_dir(self) -> Path:
        return self.data_dir / "skill-release-inbox"

    @property
    def credential_key_file(self) -> Path:
        return self.data_dir / "credential.key"

    @property
    def frontend_dist(self) -> Path:
        return self.project_root / "frontend" / "dist"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.upload_dir,
            self.run_dir,
            self.workflow_dir,
            self.avatar_dir,
            self.log_dir,
            self.skill_release_dir,
            self.skill_release_inbox_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
