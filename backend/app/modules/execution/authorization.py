"""Execution identity checks share the existing user/Skill permission facts.

Callers own transactions and locks. Mutating ordinary task transitions acquire
scheduler global before task row, then observe current identity/permission.
This is an authorization boundary, not instantaneous revocation of an already
started external operation. It never commits or impersonates a historical role.
"""
from enum import StrEnum
import hashlib
import json
from fastapi import HTTPException
from ...auth import UserContext
from ...authorization import refresh_active_user, assert_skill_permission
from ...audit_service import record_audit


class ExecutionPhase(StrEnum):
    CREATE = "create"
    CONFIRM = "confirm"
    CLAIM = "claim"
    START = "start"
    READ = "read"
    WRITE = "write"
    PUBLISH = "publish"
    CANCEL = "cancel"


class ExecutionAuthorizationRevoked(RuntimeError):
    code = "AUTHORIZATION_REVOKED"
    def __init__(self, phase):
        self.phase = ExecutionPhase(phase)
        super().__init__("任务所属账号或工具权限已变化，未开始新的执行步骤。")


def record_authorization_observation(db, execution, current, permission, phase, *, resource_type="run", action=None):
    """Record already-checked facts in the caller's transaction; never commit."""
    phase = ExecutionPhase(phase)
    facts = {"role":current.role, "department_id":current.department_id,
             "skill_id":execution.skill_id, "status":"active",
             "permission":None if permission is None else {
                 "id":permission.id,"can_run":permission.can_run,
                 "can_upload":permission.can_upload,
                 "can_create_draft":permission.can_create_draft,
                 "requires_approval":permission.requires_approval}}
    digest=hashlib.sha256(json.dumps(facts,sort_keys=True).encode()).hexdigest()
    details = {"phase": phase.value, "observation_sha256": digest}
    if action is not None:
        if action.workflow_id != execution.id:
            raise ValueError("Authorization action does not belong to workflow")
        details.update(action_id=action.id, attempt=action.attempt_count)
    record_audit(db, actor=current, action="execution.authorized",
                 resource_type=resource_type, resource_id=execution.id, details=details)


def execution_owner(db, execution, phase, *, observe=False):
    """Resolve a fixed owner/department against live records before a new phase."""
    phase = ExecutionPhase(phase)
    if phase == ExecutionPhase.CANCEL:
        raise ValueError("Cancellation must authorize the actual caller, not the task owner")
    snapshot = UserContext(user_id=execution.owner_id, display_name="", role="",
                           department_id=execution.department_id)
    try:
        current = refresh_active_user(db, snapshot)
        permission = assert_skill_permission(db, current, execution.skill_id)
    except HTTPException as error:
        if error.status_code != 403:
            raise
        raise ExecutionAuthorizationRevoked(phase) from None
    if observe:
        record_authorization_observation(db, execution, current, permission, phase)
    return current


def execution_actor(db, execution, actor, phase):
    """Authorize the actual caller; cancellation waives only the Skill grant."""
    from ...resource_policy import assert_owner
    phase=ExecutionPhase(phase)
    current=refresh_active_user(db,actor)
    if execution.department_id != current.department_id:
        raise HTTPException(404,"任务不存在。")
    assert_owner(execution.owner_id,current,"任务",execution.department_id)
    if phase != ExecutionPhase.CANCEL:
        assert_skill_permission(db,current,execution.skill_id)
    return current
