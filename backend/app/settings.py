from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


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
        for item in os.getenv("FINANCIAL_WORKER_POOLS", "python,http").split(",")
        if item.strip()
    )
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
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def frontend_dist(self) -> Path:
        return self.project_root / "frontend" / "dist"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.run_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
