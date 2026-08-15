from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .auth import UserContext
from .settings import settings

SAFE_STORAGE_COMPONENT = re.compile(r"^[0-9A-Za-z._-]+$")


def assert_owner(
    owner_id: str,
    user: UserContext,
    resource_name: str,
    department_id: str | None = None,
) -> None:
    """Employees see their own resources; admins may inspect only their department."""
    if owner_id == user.user_id:
        return
    if user.is_admin and department_id == user.department_id:
        return
    raise HTTPException(status_code=404, detail=f"{resource_name}不存在。")


def owner_list_filter(model: Any, user: UserContext) -> Any:
    """Keep employee collections owner-scoped and admin collections department-scoped."""
    if user.is_admin:
        return model.department_id == user.department_id
    return model.owner_id == user.user_id


def _safe_component(value: str, label: str) -> str:
    if not SAFE_STORAGE_COMPONENT.fullmatch(value):
        raise ValueError(f"{label}包含不安全字符")
    return value


def upload_root(owner_id: str, file_id: str) -> Path:
    return (
        settings.upload_dir
        / _safe_component(owner_id, "用户标识")
        / _safe_component(file_id, "文件标识")
    ).resolve()


def run_root(owner_id: str, run_id: str) -> Path:
    return (
        settings.run_dir
        / _safe_component(owner_id, "用户标识")
        / _safe_component(run_id, "任务标识")
    ).resolve()


def workflow_root(owner_id: str, workflow_id: str) -> Path:
    return (
        settings.workflow_dir
        / _safe_component(owner_id, "用户标识")
        / _safe_component(workflow_id, "工作流标识")
    ).resolve()
