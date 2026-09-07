from sqlalchemy.orm import Session

from .settings import settings


def task_discovery_enabled(db: Session) -> bool:
    """Task reminders use deployment defaults; retired UI overrides are ignored."""
    return settings.task_discovery_enabled
