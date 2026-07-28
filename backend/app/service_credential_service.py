from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .credential_service import decrypt_secret, encrypt_secret
from .models import ServiceCredential
from .schemas import ServiceCredentialRead

SUPPORTED_SERVICES = {"zhiyun"}


def _account_hint(account: str) -> str:
    clean = account.strip()
    if len(clean) <= 4:
        return "••••"
    if len(clean) <= 7:
        return f"{clean[:1]}•••{clean[-2:]}"
    return f"{clean[:3]}••••{clean[-4:]}"


def _get_record(
    db: Session,
    user: UserContext,
    service: str,
) -> ServiceCredential | None:
    if service not in SUPPORTED_SERVICES:
        raise HTTPException(status_code=404, detail="不支持的业务系统凭据。")
    return db.scalar(
        select(ServiceCredential).where(
            ServiceCredential.owner_id == user.user_id,
            ServiceCredential.department_id == user.department_id,
            ServiceCredential.service == service,
        )
    )


def serialize_service_credential(
    service: str,
    credential: ServiceCredential | None,
) -> ServiceCredentialRead:
    return ServiceCredentialRead(
        service=service,
        configured=credential is not None and credential.status == "configured",
        account_hint=credential.account_hint if credential else "",
        updated_at=credential.updated_at if credential else None,
    )


def get_service_credential_status(
    db: Session,
    user: UserContext,
    service: str,
) -> ServiceCredentialRead:
    return serialize_service_credential(service, _get_record(db, user, service))


def save_service_credential(
    db: Session,
    user: UserContext,
    service: str,
    account: str,
    password: str,
) -> ServiceCredentialRead:
    clean_account = account.strip()
    if not clean_account or not password:
        raise HTTPException(status_code=422, detail="账号和密码不能为空。")
    credential = _get_record(db, user, service)
    now = datetime.now(UTC)
    if credential:
        credential.account_encrypted = encrypt_secret(clean_account)
        credential.password_encrypted = encrypt_secret(password)
        credential.account_hint = _account_hint(clean_account)
        credential.status = "configured"
        credential.updated_at = now
    else:
        credential = ServiceCredential(
            id=str(uuid.uuid4()),
            owner_id=user.user_id,
            department_id=user.department_id,
            service=service,
            account_encrypted=encrypt_secret(clean_account),
            password_encrypted=encrypt_secret(password),
            account_hint=_account_hint(clean_account),
            status="configured",
            created_at=now,
            updated_at=now,
        )
        db.add(credential)
    db.commit()
    db.refresh(credential)
    return serialize_service_credential(service, credential)


def remove_service_credential(
    db: Session,
    user: UserContext,
    service: str,
) -> None:
    credential = _get_record(db, user, service)
    if credential:
        db.delete(credential)
        db.commit()


def resolve_service_credential(
    db: Session,
    owner_id: str,
    department_id: str,
    service: str,
) -> tuple[str, str]:
    credential = db.scalar(
        select(ServiceCredential).where(
            ServiceCredential.owner_id == owner_id,
            ServiceCredential.department_id == department_id,
            ServiceCredential.service == service,
            ServiceCredential.status == "configured",
        )
    )
    if not credential:
        raise RuntimeError("尚未配置智云账号，请先在任务右侧安全保存账号和密码。")
    return (
        decrypt_secret(credential.account_encrypted),
        decrypt_secret(credential.password_encrypted),
    )


def has_service_credential(
    db: Session,
    owner_id: str,
    department_id: str,
    service: str,
) -> bool:
    return (
        db.scalar(
            select(ServiceCredential.id).where(
                ServiceCredential.owner_id == owner_id,
                ServiceCredential.department_id == department_id,
                ServiceCredential.service == service,
                ServiceCredential.status == "configured",
            )
        )
        is not None
    )
