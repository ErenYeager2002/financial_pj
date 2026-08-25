from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .contracts import FeatureControlRead
from .models import PlatformFeatureControl
from .settings import settings

TASK_DISCOVERY = "task-discovery"


def task_discovery_enabled(db: Session) -> bool:
    record = db.get(PlatformFeatureControl, TASK_DISCOVERY)
    return record.enabled if record is not None else settings.task_discovery_enabled


def _task_discovery_control(db: Session) -> FeatureControlRead:
    record = db.get(PlatformFeatureControl, TASK_DISCOVERY)
    return FeatureControlRead(
        key=TASK_DISCOVERY,
        name="任务提醒自动检查",
        description="按计划使用负责人凭据只读检查智云，并生成待处理日期提醒。",
        category="automation",
        enabled=record.enabled if record is not None else settings.task_discovery_enabled,
        editable=True,
        source="administrator" if record is not None else "deployment",
        changed_by=record.changed_by if record is not None else "",
        changed_at=record.changed_at if record is not None else None,
    )


def list_feature_controls(db: Session) -> list[FeatureControlRead]:
    return [
        _task_discovery_control(db),
        FeatureControlRead(
            key="ar-hexiao-execution",
            name="应收核销正式执行",
            description="允许创建和执行会写入业务工作簿的应收核销任务。",
            category="execution",
            enabled=settings.ar_hexiao_execution_enabled,
            editable=False,
            source="deployment",
            blocked_reason="这是生产安全限制，需要修改部署配置并重启后台服务。",
        ),
        FeatureControlRead(
            key="local-session-login",
            name="账号密码登录",
            description="允许平台本地账号通过服务端会话登录。",
            category="authentication",
            enabled=settings.auth_mode in {"session", "hybrid"},
            editable=False,
            source="deployment",
            blocked_reason="认证方式需要修改部署配置并重新登录，不能在线切换。",
        ),
        FeatureControlRead(
            key="clerk-login",
            name="Clerk 登录",
            description="允许通过 Clerk 验证登录身份。",
            category="authentication",
            enabled=settings.auth_mode in {"clerk", "hybrid"},
            editable=False,
            source="deployment",
            blocked_reason="认证方式需要修改部署配置并重新登录，不能在线切换。",
        ),
    ]


def update_feature_control(
    db: Session,
    actor: UserContext,
    key: str,
    enabled: bool,
) -> FeatureControlRead:
    if key != TASK_DISCOVERY:
        known = {item.key for item in list_feature_controls(db)}
        if key not in known:
            raise HTTPException(status_code=404, detail="功能开关不存在。")
        raise HTTPException(status_code=409, detail="该开关由部署配置控制，不能在线修改。")

    record = db.get(PlatformFeatureControl, key)
    previous = task_discovery_enabled(db)
    if record is None:
        record = PlatformFeatureControl(key=key, enabled=enabled)
        db.add(record)
    record.enabled = enabled
    record.changed_by = actor.user_id
    record.changed_at = datetime.now(UTC)
    record_audit(
        db,
        actor=actor,
        action="admin.feature_control.update",
        resource_type="feature_control",
        resource_id=key,
        details={"from_enabled": previous, "to_enabled": enabled},
    )
    db.commit()
    db.refresh(record)
    return _task_discovery_control(db)
