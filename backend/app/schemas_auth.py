from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .contracts import PlatformUser


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class SessionRead(PlatformUser):
    """兼容旧 Cookie 登录接口；公开会话契约名称为 PlatformUser。"""


class SkillPermissionWrite(BaseModel):
    skill_id: str = Field(min_length=1, max_length=128)
    can_run: bool = True
    can_upload: bool = True
    can_create_draft: bool = True
    requires_approval: bool = False


class SkillPermissionRead(SkillPermissionWrite):
    pass


class SkillPermissionsReplace(BaseModel):
    permissions: list[SkillPermissionWrite] = Field(default_factory=list, max_length=200)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    initial_password: str = Field(min_length=8, max_length=256)
    role: Literal["finance_user", "skill_admin"] = "finance_user"
    department_id: str = Field(default="finance", min_length=1, max_length=128)


class AdminUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: Literal["finance_user", "skill_admin"] | None = None
    status: Literal["active", "disabled"] | None = None
    clerk_user_id: str | None = Field(default=None, max_length=128)
    clerk_organization_id: str | None = Field(default=None, max_length=128)


class AdminPasswordReset(BaseModel):
    initial_password: str = Field(min_length=8, max_length=256)


class AdminUserRead(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    department_id: str
    status: str
    must_change_password: bool
    clerk_user_id: str | None
    clerk_organization_id: str | None
    permissions: list[SkillPermissionRead]
    created_at: datetime
