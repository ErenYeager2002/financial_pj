from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .auth import UserContext
from .models import FileRecord
from .settings import settings

SAFE_NAME_PATTERN = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._()（）-]+")


def safe_filename(name: str) -> str:
    clean = SAFE_NAME_PATTERN.sub("_", Path(name).name).strip("._")
    return clean[:180] or "uploaded-file"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def save_upload(db: Session, upload: UploadFile, user: UserContext) -> FileRecord:
    file_id = str(uuid.uuid4())
    folder = settings.upload_dir / file_id
    folder.mkdir(parents=True, exist_ok=False)
    target = folder / safe_filename(upload.filename or "uploaded-file")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    digest = hashlib.sha256()
    try:
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件超过 {settings.max_upload_mb} MB 限制。",
                    )
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    record = FileRecord(
        id=file_id,
        owner_id=user.user_id,
        department_id=user.department_id,
        kind="input",
        original_name=upload.filename or target.name,
        stored_path=str(target.resolve()),
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
        sha256=digest.hexdigest(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def register_output(
    db: Session,
    path: Path,
    run_id: str,
    owner: UserContext,
    display_name: str | None = None,
) -> FileRecord:
    resolved = path.resolve()
    run_root = (settings.run_dir / run_id).resolve()
    if not resolved.is_file() or not resolved.is_relative_to(run_root):
        raise ValueError("输出文件必须位于本次运行目录内")
    record = FileRecord(
        id=str(uuid.uuid4()),
        owner_id=owner.user_id,
        department_id=owner.department_id,
        kind="output",
        original_name=display_name or path.name,
        stored_path=str(resolved),
        content_type="application/octet-stream",
        size_bytes=resolved.stat().st_size,
        sha256=sha256_file(resolved),
        run_id=run_id,
    )
    db.add(record)
    db.flush()
    return record


def copy_input_to_workspace(source: Path, target_dir: Path, role: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    target = target_dir / f"{safe_filename(role)}{suffix}"
    shutil.copy2(source, target)
    return target.resolve()
