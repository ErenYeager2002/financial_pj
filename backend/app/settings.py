from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

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
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
