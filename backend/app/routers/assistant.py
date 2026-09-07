from __future__ import annotations

import sys

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..agent_model_gateway import (
    AgentModelStreamStats,
    build_agent_model_payload,
    iter_agent_model_stream,
    open_agent_model_stream,
    resolve_agent_model_config,
    save_agent_model_trace,
)
from ..assistant_chat_service import (
    append_message,
    get_conversation,
    get_latest_conversation,
    list_conversations,
)
from ..assistant_profile_service import (
    admin_profile,
    assistant_status,
    configure_assistant_profile,
    remove_assistant_profile,
)
from ..audit_service import record_audit
from ..auth import UserContext, get_current_user, require_admin
from ..contracts import (
    AdminAssistantProfile,
    AssistantConversationRead,
    AssistantConversationSummary,
    AssistantMessageRead,
    AssistantStatus,
    RunDetail,
    SkillDetail,
    TaskDraft,
)
from ..database import SessionLocal, get_db
from ..draft_service import (
    confirm_task_draft,
    delete_task_draft,
    get_task_draft,
    list_agent_skill_details,
    prepare_task_draft,
    update_task_draft,
)
from ..run_service import serialize_run
from ..schemas_assistant import (
    AdminAssistantProfileWrite,
    AgentModelRequest,
    AgentPrepareRequest,
    AssistantMessageWrite,
    AssistantPrepareRequest,
    TaskDraftUpdate,
)

router = APIRouter(tags=["assistant"])


@router.get(
    "/api/assistant/conversations",
    response_model=list[AssistantConversationSummary],
)
def assistant_conversations(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[AssistantConversationSummary]:
    return list_conversations(db, user)


@router.get(
    "/api/assistant/conversations/latest",
    response_model=AssistantConversationRead | None,
)
def latest_assistant_conversation(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AssistantConversationRead | None:
    return get_latest_conversation(db, user)


@router.get(
    "/api/assistant/conversations/{session_id}",
    response_model=AssistantConversationRead,
)
def assistant_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AssistantConversationRead:
    return get_conversation(db, user, session_id)


@router.post(
    "/api/assistant/conversations/{session_id}/messages",
    response_model=AssistantMessageRead,
    status_code=201,
)
def append_assistant_conversation_message(
    session_id: str,
    body: AssistantMessageWrite,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AssistantMessageRead:
    message = append_message(
        db,
        user,
        session_id,
        body.role,
        body.content,
        body.data,
    )
    db.commit()
    return message


@router.post("/api/assistant/model/chat/completions", include_in_schema=False)
@router.post(
    "/api/assistant/model",
    responses={
        200: {
            "description": "模型流式响应。",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def stream_agent_model(
    body: AgentModelRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
    model_session: str | None = Header(
        default=None,
        alias="X-Financial-Model-Session",
        max_length=128,
        description="可选的模型会话标识；按当前用户隔离并脱敏后用于上游提示缓存。",
    ),
) -> StreamingResponse:
    """给服务端 Pi Runtime 提供受部门模型配置约束的 SSE 上游。"""
    config = resolve_agent_model_config(db, user, body.connection_id, body.model)
    try:
        payload = build_agent_model_payload(config, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session_options: dict[str, str] = {}
    if config.provider == "opencode_go" and model_session:
        session_options["session_id"] = f"assistant:{user.user_id}:{model_session}"
    stream_context = open_agent_model_stream(config, payload, **session_options)
    stats = AgentModelStreamStats()
    try:
        response = stream_context.__enter__()
        response.raise_for_status()
    except httpx.HTTPError as exc:
        stream_context.__exit__(*sys.exc_info())
        stats.fail(f"upstream_http_{getattr(exc.response, 'status_code', 'error')}")
        save_agent_model_trace(db, user, config, stats)
        db.commit()
        raise HTTPException(status_code=502, detail="模型服务当前不可用。") from exc
    except Exception as exc:
        stream_context.__exit__(*sys.exc_info())
        stats.fail(type(exc).__name__)
        save_agent_model_trace(db, user, config, stats)
        db.commit()
        raise HTTPException(status_code=502, detail="模型网关连接失败。") from exc

    def body_iterator():
        try:
            yield from iter_agent_model_stream(response, stats)
        finally:
            if stats.status == "running":
                stats.fail("stream_cancelled")
            with SessionLocal() as trace_db:
                save_agent_model_trace(trace_db, user, config, stats)
                trace_db.commit()
            stream_context.__exit__(None, None, None)

    return StreamingResponse(
        body_iterator(),
        media_type=response.headers.get("content-type", "text/event-stream"),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/assistant/status", response_model=AssistantStatus)
def get_assistant_status(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AssistantStatus:
    return assistant_status(db, user)


@router.get("/api/assistant/skills", response_model=list[SkillDetail])
def list_assistant_skills(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[SkillDetail]:
    """Return the Skill directory that the current Platform User may turn into a draft."""
    return list_agent_skill_details(db, user)


@router.post("/api/assistant/prepare-from-recommendation", response_model=TaskDraft)
def prepare_from_agent_recommendation(
    body: AgentPrepareRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> TaskDraft:
    """校验 Pi 工具返回的推荐，并复用现有草稿安全边界。"""
    draft = prepare_task_draft(
        db,
        user,
        body.message,
        body.file_ids,
        recommendation=body.recommendation,
        trace_purpose="agent_tool",
    )
    record_audit(
        db,
        actor=user,
        action="draft.prepare.agent",
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
