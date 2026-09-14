"""Lock user-selected material changes while their workflow is in progress."""
from sqlalchemy import select
from .models import WorkflowAction, WorkflowBatch, WorkflowSession

TERMINAL = ("succeeded", "failed", "cancelled")
MESSAGE = "当前有任务正在进行，任务材料已锁定；任务结束后可选择、替换或恢复材料。"


def material_edit_state(db, user, skill_id):
    scope = dict(owner_id=user.user_id, department_id=user.department_id, skill_id=skill_id)
    batch = db.scalar(select(WorkflowBatch.id).filter_by(**scope).where(WorkflowBatch.state.not_in(TERMINAL)).limit(1))
    single = db.scalar(select(WorkflowSession.id).filter_by(**scope).where(
        WorkflowSession.batch_id.is_(None), WorkflowSession.state.not_in(TERMINAL),
        WorkflowSession.stage.not_in(("awaiting_date", "awaiting_date_confirmation", "awaiting_files"))).limit(1))
    action = db.scalar(select(WorkflowAction.id).join(WorkflowSession).where(
        WorkflowSession.owner_id == user.user_id, WorkflowSession.department_id == user.department_id,
        WorkflowSession.skill_id == skill_id, WorkflowAction.state.in_(("queued", "running"))).limit(1))
    locked = bool(batch or single or action)
    return {"locked": locked, "reason": MESSAGE if locked else ""}


def assert_material_editable(db, user, skill_id):
    from .workflow_material_service import MaterialVersionConflict
    if material_edit_state(db, user, skill_id)["locked"]:
        raise MaterialVersionConflict(MESSAGE)
