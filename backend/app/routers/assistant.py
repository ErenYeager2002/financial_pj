from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..assistant_profile_service import (
    admin_profile,
    assistant_status,
    configure_assistant_profile,
    remove_assistant_profile,
)
from ..audit_service import record_audit
from ..auth import UserContext, get_current_user, require_admin
from ..contracts import AdminAssistantProfile, AssistantStatus, RunDetail, TaskDraft
from ..database import get_db
from ..draft_service import (
    confirm_task_draft,
    delete_task_draft,
    get_task_draft,
    prepare_task_draft,
    update_task_draft,
)
from ..run_service import serialize_run
from ..schemas_assistant import (
    AdminAssistantProfileWrite,
    AssistantPrepareRequest,
    TaskDraftUpdate,
)

router = APIRouter(tags=["assistant"])


@router.get("/api/assistant/status", response_model=AssistantStatus)
def get_assistant_status(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AssistantStatus:
    return assistant_status(db, user)


@router.post("/api/assistant/prepare", response_model=TaskDraft)
def prepare(
    body: AssistantPrepareRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> TaskDraft:
    draft = prepare_task_draft(db, user, body.message, body.file_ids)
    record_audit(
        db,
        actor=user,
        action="draft.prepare",
        resource_type="task_draft",
        resource_id=draft.id,
        details={
            "skill_id": draft.skill_id,
            "state": draft.state,
            "file_count": len(draft.file_hashes),
        },
    )
    db.commit()
    return draft


@router.get("/api/task-drafts/{draft_id}", response_model=TaskDraft)
def get_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> TaskDraft:
    return get_task_draft(db, draft_id, user)


@router.patch("/api/task-drafts/{draft_id}", response_model=TaskDraft)
def update_draft(
    draft_id: str,
    body: TaskDraftUpdate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> TaskDraft:
    draft = update_task_draft(db, draft_id, user, body)
    record_audit(
        db,
        actor=user,
        action="draft.update",
        resource_type="task_draft",
        resource_id=draft.id,
        details={"state": draft.state, "file_count": len(draft.file_hashes)},
    )
    db.commit()
    return draft


@router.post("/api/task-drafts/{draft_id}/confirm", response_model=RunDetail)
def confirm_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunDetail:
    run = confirm_task_draft(db, draft_id, user)
    record_audit(
        db,
        actor=user,
        action="draft.confirm",
        resource_type="task_draft",
        resource_id=draft_id,
        details={"run_id": run.id, "skill_id": run.skill_id},
    )
    db.commit()
    return serialize_run(run)


@router.delete("/api/task-drafts/{draft_id}", status_code=204)
def delete_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> Response:
    delete_task_draft(db, draft_id, user)
    record_audit(
        db,
        actor=user,
        action="draft.delete",
        resource_type="task_draft",
        resource_id=draft_id,
    )
    db.commit()
    return Response(status_code=204)


@router.get("/api/admin/assistant-profile", response_model=AdminAssistantProfile)
def get_admin_profile(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AdminAssistantProfile:
    require_admin(user)
    return admin_profile(db, user)


@router.put("/api/admin/assistant-profile", response_model=AdminAssistantProfile)
def put_admin_profile(
    body: AdminAssistantProfileWrite,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AdminAssistantProfile:
    require_admin(user)
    profile = configure_assistant_profile(db, user, body.connection_id, body.model)
    record_audit(
        db,
        actor=user,
        action="assistant_profile.update",
        resource_type="model_profile",
        details={"connection_id": body.connection_id, "model": body.model},
    )
    db.commit()
    return profile


@router.delete("/api/admin/assistant-profile", status_code=204)
def delete_admin_profile(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> Response:
    require_admin(user)
    remove_assistant_profile(db, user)
    record_audit(
        db,
        actor=user,
        action="assistant_profile.delete",
        resource_type="model_profile",
    )
    db.commit()
    return Response(status_code=204)
