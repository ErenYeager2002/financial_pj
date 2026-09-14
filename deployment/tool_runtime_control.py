"""Privileged deployment transport executed in the API container, not an API route.

Requests arrive over stdin. A normal authenticated administrator session is required.
Only the affected availability row is locked during filesystem cutover.
"""
import json
import sys
from sqlalchemy import func, select
from app.auth import UserContext
from app.auth_service import get_session_user
from app.database import SessionLocal
from app.models import SkillAvailability, AuditEvent, WorkflowAction, WorkflowSession
from app.audit_service import record_audit
from app.registry import registry
from app.scheduler import acquire_claim_lock
from app.skill_availability_service import get_availability, transition_availability


def main():
    registry.refresh()
    db = SessionLocal()
    held = False
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                user = get_session_user(db, request.get("token", ""))
                if not user or user.role != "skill_admin" or user.must_change_password:
                    raise RuntimeError("需要有效的管理员会话")
                actor = UserContext(user.id, user.display_name, user.role, user.department_id, user.username)
                skill_id = request["skill_id"]
                operation = request["operation"]
                if operation == "release_guard":
                    db.rollback(); held = False
                    result = {}
                else:
                    if held:
                        raise RuntimeError("切换锁持有期间只允许释放锁")
                    if operation == "guard":
                        # Lock only this tool. Other tools keep accepting and claiming work.
                        db.scalar(select(SkillAvailability).where(SkillAvailability.skill_id == skill_id).with_for_update())
                    else:
                        acquire_claim_lock(db)
                    state = get_availability(db, skill_id)
                    actions = db.scalar(select(func.count()).select_from(WorkflowAction).join(
                        WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id).where(
                        WorkflowSession.skill_id == skill_id,
                        WorkflowAction.state.in_(("queued", "running")),
                    )) or 0
                    state = state.model_copy(update={"active_work_count": state.active_work_count + actions})
                    deployment_id = request.get("deployment_id", "")
                    receipt = None
                    if operation in {"pause", "disable", "resume"}:
                        if not deployment_id:
                            raise RuntimeError("缺少发布记录编号")
                        receipt = db.scalar(select(AuditEvent).where(
                            AuditEvent.resource_type == "tool_deployment",
                            AuditEvent.resource_id == deployment_id,
                            AuditEvent.action == "deploy.tool." + operation,
                            AuditEvent.actor_id == actor.user_id,
                        ))
                    if receipt:
                        details = json.loads(receipt.details_json)
                        if details.get("generation") != state.generation or details.get("skill_id") != skill_id:
                            raise RuntimeError("已完成操作之后工具状态又发生变化，停止自动处理")
                        result = state.model_dump(mode="json")
                        db.rollback()
                        print(json.dumps({"ok": True, "result": result, "guarded": held}), flush=True)
                        continue
                    expected = request.get("generation")
                    if expected is not None and state.generation != expected:
                        raise RuntimeError("工具状态已被其他操作修改，停止自动发布")
                    if operation == "status":
                        result = state.model_dump(mode="json")
                    elif operation in {"pause", "disable", "resume"}:
                        required = {"pause": {"enabled"}, "disable": {"draining"}, "resume": {"draining", "disabled"}}[operation]
                        if state.state not in required:
                            raise RuntimeError("工具状态不属于本次发布，拒绝修改")
                        if operation == "disable" and state.active_work_count:
                            raise RuntimeError("目标工具仍有活动任务或操作")
                        target = {"pause": "draining", "disable": "disabled", "resume": "enabled"}[operation]
                        reason = {"pause": "工具更新中，等待现有任务完成", "disable": "工具更新中，正在切换版本", "resume": "工具更新处理完成"}[operation]
                        if operation != "pause":
                            owned = db.scalar(select(AuditEvent.id).where(
                                AuditEvent.resource_type == "tool_deployment",
                                AuditEvent.resource_id == deployment_id,
                                AuditEvent.action == "deploy.tool.pause",
                                AuditEvent.actor_id == actor.user_id,
                            ))
                            if owned is None:
                                raise RuntimeError("当前工具暂停不属于本次发布")
                        # The receipt and availability transition commit together.
                        record_audit(db, actor=actor, action="deploy.tool." + operation,
                            resource_type="tool_deployment", resource_id=deployment_id,
                            details={"skill_id": skill_id, "generation": state.generation + 1})
                        result = transition_availability(db, actor, skill_id, target, reason, acquire_lock=False).model_dump(mode="json")
                    elif operation == "guard":
                        if state.state != "disabled" or state.active_work_count:
                            raise RuntimeError("目标工具仍有任务，尚不能切换")
                        held = True
                        result = {"guarded": True}
                    else:
                        raise RuntimeError("未知发布操作")
                    if not held:
                        db.rollback()
                print(json.dumps({"ok": True, "result": result, "guarded": held}), flush=True)
            except Exception as exc:
                db.rollback(); held = False
                detail = getattr(exc, "detail", None)
                message = str(detail) if detail else str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                print(json.dumps({"ok": False, "error": message, "guarded": False}), flush=True)
    finally:
        db.rollback(); db.close()

if __name__ == "__main__":
    main()
