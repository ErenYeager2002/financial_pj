from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .auth import UserContext
from .auth_models import User
from .settings import settings

MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _detected_content_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _stored_avatar_path(storage_name: str) -> Path:
    root = settings.avatar_dir.resolve()
    target = (root / storage_name).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=409, detail="头像存储路径异常。")
    return target


async def save_avatar(db: Session, upload: UploadFile, user: UserContext) -> User:
    content = await upload.read(MAX_AVATAR_BYTES + 1)
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="头像文件不能超过 2 MB。",
        )
    detected_type = _detected_content_type(content)
    if detected_type is None or upload.content_type not in {None, "", detected_type}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="头像仅支持 JPEG、PNG 或 WebP 图片。",
        )
    stored = db.get(User, user.user_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="用户不存在。")

    settings.avatar_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{user.user_id}/{uuid.uuid4().hex}{AVATAR_TYPES[detected_type]}"
    target = _stored_avatar_path(storage_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    old_path = (
        _stored_avatar_path(stored.avatar_storage_name) if stored.avatar_storage_name else None
    )
    try:
        temporary.write_bytes(content)
        os.replace(temporary, target)
        stored.avatar_storage_name = storage_name
        stored.avatar_content_type = detected_type
        stored.avatar_updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(stored)
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        db.rollback()
        raise
    if old_path and old_path != target:
        old_path.unlink(missing_ok=True)
    return stored


def avatar_file(db: Session, user: UserContext) -> tuple[Path, str, datetime]:
    stored = db.get(User, user.user_id)
    if (
        stored is None
        or not stored.avatar_storage_name
        or not stored.avatar_content_type
        or not stored.avatar_updated_at
    ):
        raise HTTPException(status_code=404, detail="尚未上传头像。")
    target = _stored_avatar_path(stored.avatar_storage_name)
    if not target.is_file():
        raise HTTPException(status_code=410, detail="头像文件已经不存在。")
    return target, stored.avatar_content_type, stored.avatar_updated_at
