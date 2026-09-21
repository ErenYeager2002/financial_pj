"""Audited administrator stop for a disabled owner, without impersonation."""
from uuid import uuid4
import fcntl
from fastapi import HTTPException
from .auth import require_admin
from .auth_models import User
from .authorization import refresh_active_user
from .audit_service import record_audit
from .scheduler import acquire_claim_lock
from . import pi_runtime_service as runtime


def _authorize(db, actor, owner_id):
    current = refresh_active_user(db, actor)
    require_admin(current)
    owner = db.get(User, owner_id, populate_existing=True)
    if owner is None or owner.department_id != current.department_id:
        raise HTTPException(404, "用户或 Pi 会话不存在。")
    if owner.status != "disabled":
        raise HTTPException(409, "该入口仅用于停止已停用账号的 Pi 会话。")
    return current, owner.department_id


def stop_disabled_owner_session(db, actor, owner_id: str, session_id: str) -> dict:
    current, department = _authorize(db, actor, owner_id)
    session_id, path, _ = runtime._session_record_for_owner(owner_id, department, session_id)
    # Wait for the ordinary owner operation without holding scheduler global.
    with path.with_suffix(".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        acquire_claim_lock(db)
        current, department = _authorize(db, actor, owner_id)
        session_id, _, _ = runtime._session_record_for_owner(owner_id, department, session_id)
        details = {"owner_id": owner_id, "request_id": str(uuid4()), "reason": "owner_disabled"}
        record_audit(db, actor=current, action="pi.session.admin_stop_requested",
                     resource_type="pi_session", resource_id=session_id, details=details)
        # Record who authorized the stop before dispatch; never hold global
        # across transport. A lost reply remains an auditable unknown outcome.
        db.commit()
        try:
            result = runtime._request_runtime({"owner": runtime.owner_scope_key(owner_id, department),
                "session_id": session_id, "operation": "stop", "payload": {}})
            if result.get("running") is not False or result.get("environment_running") is not False:
                raise HTTPException(503, "Pi 会话停止状态尚未确认。")
        except Exception as error:
            db.rollback()
            record_audit(db, actor=current, action="pi.session.admin_stop_unknown",
                         resource_type="pi_session", resource_id=session_id,
                         details={**details, "error_type": type(error).__name__})
            db.commit()
            raise
        record_audit(db, actor=current, action="pi.session.admin_stop",
                     resource_type="pi_session", resource_id=session_id, details=details)
        db.commit()
        return {"running": False, "environment_running": False}
