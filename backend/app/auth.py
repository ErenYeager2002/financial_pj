from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, Query, status


@dataclass(frozen=True)
class UserContext:
    user_id: str
    display_name: str
    role: str
    department_id: str = "finance"

    @property
    def is_admin(self) -> bool:
        return self.role == "skill_admin"


def get_current_user(
    x_user_id: str = Header(default="demo-user"),
    x_user_name: str = Header(default=""),
    x_user_role: str = Header(default="finance_user"),
    x_department_id: str = Header(default="finance"),
) -> UserContext:
    role = x_user_role if x_user_role in {"finance_user", "skill_admin"} else "finance_user"
    display_name = x_user_name.strip() or ("Skill 管理员" if role == "skill_admin" else "财务员工")
    return UserContext(
        user_id=x_user_id.strip() or "demo-user",
        display_name=display_name,
        role=role,
        department_id=x_department_id.strip() or "finance",
    )


def get_sse_user(
    user_id: str = Query(default="demo-user"),
    role: str = Query(default="finance_user"),
    department_id: str = Query(default="finance"),
) -> UserContext:
    return UserContext(
        user_id=user_id,
        display_name=user_id,
        role=role if role in {"finance_user", "skill_admin"} else "finance_user",
        department_id=department_id,
    )


def require_admin(user: UserContext) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有 Skill 管理员可以执行此操作。",
        )
