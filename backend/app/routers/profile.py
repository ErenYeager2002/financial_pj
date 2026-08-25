from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..audit_service import record_audit
from ..auth import UserContext, get_current_user
from ..auth_models import User
from ..avatar_service import avatar_file, save_avatar
from ..contracts import PlatformUser
from ..database import get_db

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _platform_user(user: UserContext, stored: User) -> PlatformUser:
    return PlatformUser(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        department_id=user.department_id,
        must_change_password=stored.must_change_password,
        auth_provider=user.auth_provider,
        avatar_updated_at=stored.avatar_updated_at,
    )


@router.post("/avatar", response_model=PlatformUser)
async def upload_avatar(
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> PlatformUser:
    stored = await save_avatar(db, upload, user)
    record_audit(
        db,
        actor=user,
        action="profile.avatar.update",
        resource_type="user",
        resource_id=user.user_id,
        details={"content_type": stored.avatar_content_type},
    )
    db.commit()
    return _platform_user(user, stored)


@router.get("/avatar")
def get_avatar(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> FileResponse:
    path, content_type, updated_at = avatar_file(db, user)
    return FileResponse(
        path,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Last-Modified": updated_at.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        },
    )
