from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .ar_execution_service import ArEvidencePage, ArExecutionRead, read_evidence_page, read_execution
from .ar_execution_recovery import ArRecoveryRequest, recover_execution
from .ar_result_details import ArResultPage, read_result_page
from .auth import UserContext, get_current_user, get_sse_user, require_admin
from .auth_service import bootstrap_admin
from .authorization import allowed_skill_ids, assert_skill_permission, get_skill_permission
from .contracts import (
    AdminSkillDetail,
    PlatformFile,
    PlatformFileDetail,
    PlatformFileGroupSummaryPage,
    PlatformFileOptionPage,
    PlatformFilePage,
    PlatformHealth,
    PlatformUser,
    RuntimeHealth,
    RegistryReloadResponse,
    RunApprovalRead,
    RunDetail,
    RunEventRead,
    RunPage,
    SkillDetail,
    SkillSummary,
    StepRunRead,
    TaskCenterPage,
    TaskCenterReferenceType,
    TaskCenterViewState,
    Workbench,
    domain_contract_schemas,
)
from .database import SessionLocal, get_db, init_db
from .file_service import (
    get_file_detail,
    list_file_groups,
    list_files_page,
    list_selectable_input_files_page,
    serialize_file,
)
from .model_providers import list_public_providers
from .model_service import (
    connect_api_key,
    list_connections,
    refresh_connection,
    remove_connection,
    resolve_runtime_config,
    select_model,
)
from .models import FileRecord, RunEvent, RunRecord
from .orchestrator import interpret_parameters
from .redaction import sanitize_text, sanitize_value
from .registry import RegisteredSkill, registry
from .resource_policy import assert_owner
from .runtime_health_service import runtime_health
from .routers import admin_approvals as admin_approvals_router
from .routers import admin_observability as admin_observability_router
from .routers import admin_skill_dedications as admin_skill_dedications_router
from .routers import admin_skills as admin_skills_router
from .routers import admin_users as admin_users_router
from .routers import admin_workflows as admin_workflows_router
from .routers import assistant as assistant_router
from .routers import audit as audit_router
from .routers import auth as auth_router
from .routers import profile as profile_router
from .routers import pi_harness as pi_harness_router
from .routers import pi_runtime as pi_runtime_router
from .routers import task_reminders as task_reminders_router
from .run_approval_service import list_run_approvals
from .run_service import (
    TERMINAL_STATES,
    cancel_run,
    confirm_run,
    create_run,
    get_run_or_404,
    list_runs_page,
    retry_run,
    retry_status,
    serialize_run,
)
from .run_step_service import list_run_steps
from .schemas import (
    InterpretRequest,
    InterpretResponse,
    ModelConnectionRead,
    ModelConnectRequest,
    ModelProviderRead,
    ModelSelectRequest,
    RunActionResponse,
    RunCreate,
    ServiceCredentialRead,
    ServiceCredentialWrite,
    WorkflowAgentActionRequest,
    WorkflowAgentActionResponse,
    WorkflowAgentContext,
    WorkflowBatchFetchedDataSupplement,
    WorkflowBatchRead,
    WorkflowBatchStart,
    WorkflowCreate,
    WorkflowFetchedDataRead,
    WorkflowFetchedDataSupplement,
    WorkflowFetchedSnapshotRead,
    WorkflowFilesUpdate,
    WorkflowMaterialSetRead,
    WorkflowMessageCreate,
    WorkflowRead,
    WorkflowReusableFilesRead,
    WorkflowStart,
)
from .schemas_assistant import MAX_ASSISTANT_FILE_IDS
from .security import origin_guard
from .service_credential_service import (
    get_service_credential_status,
    remove_service_credential,
    save_service_credential,
)
from .settings import settings
from .skill_execution_experiences import SUPPORTING_SKILL_IDS
from .storage import delete_upload, save_upload
from .task_center_service import query_task_center
from .workbench_service import get_workbench
from .workflow_constants import is_background_model_connection
from .workflow_material_service import (
    MaterialVersionConflict,
    list_material_sets,
    restore_material_set,
    serialize_material_set,
)
from .workflow_orchestrator import is_explicit_workflow_cancel_request
from .workflow_service import (
    apply_workflow_agent_action,
    cancel_workflow,
    cancel_workflow_batch,
    confirm_batch_fetched_data_review,
    confirm_fetched_data_review,
    create_workflow,
    get_workflow_batch_or_404,
    get_workflow_or_404,
    list_fetched_snapshot_options,
    list_workflow_batches,
    list_workflows,
    read_batch_fetched_data,
    read_workflow_fetched_data,
    request_batch_fetched_data_supplement,
    request_fetched_data_supplement,
    rebuild_failed_workflow,
    reset_workflow,
    retry_workflow_batch,
    reusable_workflow_files,
    send_workflow_message,
    serialize_workflow,
    serialize_workflow_batch,
    start_workflow,
    start_workflow_batch,
    supplement_audit_summary,
    update_workflow_files,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if (
        settings.environment == "production"
        and not settings.session_cookie_secure
        and os.getenv("FINANCIAL_ALLOW_HTTP", "false").strip().lower() != "true"
    ):
        raise RuntimeError(
            "生产环境必须设置 FINANCIAL_SESSION_COOKIE_SECURE=true（并要求 HTTPS）。"
        )
    settings.ensure_directories()
    init_db()
    registry.refresh()
    with SessionLocal() as db:
        bootstrap_admin(db)
    async def recover_native_runs():
        from .native_skill_service import reap_abandoned_runs
        def recover():
            with SessionLocal() as recovery_db:
                reap_abandoned_runs(recovery_db)
        while True:
            try:
                await asyncio.to_thread(recover)
            except Exception:
                logging.getLogger(__name__).exception("Native Skill recovery failed")
            await asyncio.sleep(60)
    native_recovery = asyncio.create_task(recover_native_runs())
    try:
        yield
    finally:
        native_recovery.cancel()
        try:
            await native_recovery
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def platform_openapi() -> dict[str, object]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description="财务 Skill 平台受控 API。OpenAPI 是 Next.js 前端类型的唯一来源。",
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas.update(domain_contract_schemas())
    app.openapi_schema = schema
    return schema


app.openapi = platform_openapi
app.include_router(auth_router.router)
app.include_router(profile_router.router)
app.include_router(pi_harness_router.router)
app.include_router(pi_runtime_router.router)
app.include_router(admin_approvals_router.router)
app.include_router(admin_observability_router.router)
app.include_router(admin_skill_dedications_router.router)
app.include_router(admin_skills_router.router)
app.include_router(admin_skills_router.source_router)
app.include_router(admin_skills_router.availability_router)
app.include_router(admin_skills_router.rollout_router)
app.include_router(admin_users_router.router)
app.include_router(admin_workflows_router.router)
app.include_router(audit_router.router)
app.include_router(assistant_router.router)
app.include_router(task_reminders_router.router)
app.include_router(task_reminders_router.admin_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(origin_guard)

_workflow_timing_logger = logging.getLogger("financial.workflow_timing")


def _workflow_timing_path(path: str) -> str:
    return re.sub(r"/(workflows|workflow-batches)/[^/]+", r"/\1/{id}", path)


@app.middleware("http")
async def workflow_api_timing(request, call_next):
    if settings.environment != "development" or not request.url.path.startswith(
        ("/api/workflows", "/api/workflow-batches")
    ):
        return await call_next(request)
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        _workflow_timing_logger.info(
            "path=%s method=%s status=error duration_ms=%d",
            _workflow_timing_path(request.url.path),
            request.method,
            round((time.perf_counter() - started_at) * 1000),
        )
        raise
    _workflow_timing_logger.info(
        "path=%s method=%s status=%d duration_ms=%d",
        _workflow_timing_path(request.url.path),
        request.method,
        response.status_code,
        round((time.perf_counter() - started_at) * 1000),
    )
    return response


@app.get("/api/health", response_model=PlatformHealth)
def health() -> PlatformHealth:
    return PlatformHealth(
        status="ok",
        name=settings.app_name,
        environment=settings.environment,
        skills=len(registry.list(include_disabled=True)),
        registry_errors=registry.errors,
        configured_workers=dict(settings.worker_counts),
        configured_execution_capacity=sum(count for _, count in settings.worker_counts),
    )


@app.get("/api/health/readiness", response_model=RuntimeHealth)
def health_readiness(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RuntimeHealth:
    """Return measured local queue and Worker state for the management UI."""
    return runtime_health(db, user)


@app.get("/api/session", response_model=PlatformUser)
def session(
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlatformUser:
    from .auth_models import User as UserModel

    stored = db.get(UserModel, user.user_id)
    return PlatformUser(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        department_id=user.department_id,
        must_change_password=bool(stored and stored.must_change_password),
        auth_provider=user.auth_provider,
        avatar_updated_at=stored.avatar_updated_at if stored else None,
    )


@app.get("/api/skills", response_model=list[SkillDetail | AdminSkillDetail])
def list_skills(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[SkillDetail | AdminSkillDetail]:
    skills = registry.list(include_disabled=user.is_admin)
    if not user.is_admin:
        allowed = allowed_skill_ids(db, user)
        skills = [item for item in skills if item.manifest.id in allowed]
    return [
        item.public_dict(include_schema=True)
        if user.is_admin
        else item.employee_dict(include_schema=True)
        for item in skills
    ]


@app.get("/api/skills/{skill_id}", response_model=SkillDetail | AdminSkillDetail)
def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> SkillDetail | AdminSkillDetail:
    skill = registry.get(skill_id, include_unpublished=user.is_admin)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    if not user.is_admin and skill_id not in allowed_skill_ids(db, user):
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    return (
        skill.public_dict(include_schema=True)
        if user.is_admin
        else skill.employee_dict(include_schema=True)
    )


def _catalog_skills_for_user(db: Session, user: UserContext) -> list[RegisteredSkill]:
    """返回目录可见的已发布和辅助 Skill，复用统一的权限规则。"""
    skills = registry.list(include_disabled=False)
    if not user.is_admin:
        allowed = allowed_skill_ids(db, user)
        skills = [item for item in skills if item.manifest.id in allowed]
    visible_ids = {item.manifest.id for item in skills}
    for skill_id in sorted(SUPPORTING_SKILL_IDS):
        supporting = registry.get(skill_id, include_unpublished=True)
        if (
            supporting
            and supporting.manifest.ui is not None
            and supporting.manifest.id not in visible_ids
        ):
            skills.append(supporting)
    skills.sort(key=lambda item: (item.manifest.category, item.manifest.name))
    return skills


@app.get("/api/catalog/skills", response_model=list[SkillDetail])
def list_catalog_skills(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[SkillDetail]:
    """返回员工安全视图；管理员访问时也不暴露执行入口和来源路径。"""

    skills = _catalog_skills_for_user(db, user)
    return [SkillDetail.model_validate(item.employee_dict(include_schema=True)) for item in skills]


@app.get("/api/catalog/skill-summaries", response_model=list[SkillSummary])
def list_catalog_skill_summaries(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[SkillSummary]:
    """返回 Skill 中心使用的轻量员工安全目录。"""

    skills = _catalog_skills_for_user(db, user)
    return [
        SkillSummary.model_validate(item.employee_dict(include_schema=False)) for item in skills
    ]


@app.get("/api/catalog/skills/{skill_id}", response_model=SkillDetail)
def get_catalog_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> SkillDetail:
    supporting_entry = skill_id in SUPPORTING_SKILL_IDS
    skill = registry.get(skill_id, include_unpublished=supporting_entry)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    if skill.manifest.ui is None:
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    if not supporting_entry and not user.is_admin and skill_id not in allowed_skill_ids(db, user):
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    return SkillDetail.model_validate(skill.employee_dict(include_schema=True))


@app.post("/api/skills/{skill_id}/interpret", response_model=InterpretResponse)
def interpret(
    skill_id: str,
    body: InterpretRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> InterpretResponse:
    skill = registry.get(skill_id, include_unpublished=user.is_admin)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    assert_skill_permission(db, user, skill_id)
    llm_config = resolve_runtime_config(
        db,
        user,
        body.model_connection_id,
        body.model,
    )
    parameters, missing, source, notes = interpret_parameters(
        skill,
        body.message,
        body.parameters,
        llm_config,
    )
    return InterpretResponse(parameters=parameters, missing=missing, source=source, notes=notes)


@app.get("/api/model-connections", response_model=list[ModelConnectionRead])
def model_connections(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[ModelConnectionRead]:
    return list_connections(db, user)


@app.get("/api/model-providers", response_model=list[ModelProviderRead])
def model_providers(
    user: UserContext = Depends(get_current_user),
) -> list[ModelProviderRead]:
    return list_public_providers(include_admin_only=user.is_admin)


@app.post("/api/model-connections", response_model=ModelConnectionRead)
def connect_model(
    body: ModelConnectRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ModelConnectionRead:
    return connect_api_key(
        db,
        user,
        body.api_key,
        provider_id=body.provider_id,
        base_url=body.base_url,
        model=body.model,
    )


@app.patch(
    "/api/model-connections/{connection_id}",
    response_model=ModelConnectionRead,
)
def update_model(
    connection_id: str,
    body: ModelSelectRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ModelConnectionRead:
    return select_model(db, user, connection_id, body.selected_model)


@app.post(
    "/api/model-connections/{connection_id}/refresh",
    response_model=ModelConnectionRead,
)
def refresh_model(
    connection_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ModelConnectionRead:
    return refresh_connection(db, user, connection_id)


@app.delete("/api/model-connections/{connection_id}", status_code=204)
def delete_model(
    connection_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> None:
    remove_connection(db, user, connection_id)


@app.get(
    "/api/service-credentials/{service}",
    response_model=ServiceCredentialRead,
)
def service_credential(
    service: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ServiceCredentialRead:
    return get_service_credential_status(db, user, service)


@app.put(
    "/api/service-credentials/{service}",
    response_model=ServiceCredentialRead,
)
def update_service_credential(
    service: str,
    body: ServiceCredentialWrite,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ServiceCredentialRead:
    return save_service_credential(db, user, service, body.account, body.password)


@app.delete("/api/service-credentials/{service}", status_code=204)
def delete_service_credential(
    service: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> None:
    remove_service_credential(db, user, service)


@app.post("/api/files", response_model=PlatformFile)
async def upload_file(
    upload: UploadFile = File(...),
    role: str = Form(default=""),
    skill_id: str = Form(default=""),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> PlatformFile:
    skill_id = skill_id.strip()
    skill = registry.get(skill_id, include_unpublished=user.is_admin) if skill_id else None
    if skill_id and not skill:
        raise HTTPException(status_code=422, detail="上传文件关联的 Skill 不存在或当前不可用。")
    if skill and skill.manifest.handler.adapter == "workflow":
        from .scheduler import acquire_claim_lock
        from .workflow_material_lock import assert_material_editable
        acquire_claim_lock(db)
        try:
            assert_material_editable(db, user, skill_id)
        except MaterialVersionConflict as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = await save_upload(
        db,
        upload,
        user,
        skill_id=skill.manifest.id if skill else "",
        skill_name=skill.manifest.name if skill else "",
        skill_version=skill.manifest.version if skill else "",
    )
    record_audit(
        db,
        actor=user,
        action="file.upload",
        resource_type="file",
        resource_id=record.id,
        details={
            "kind": record.kind,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "skill_id": record.skill_id,
            "role": role,
        },
    )
    db.commit()
    return serialize_file(db, record).model_copy(
        update={"role": role},
    )


def _file_list_parameters(page: int, page_size: int, query: str) -> tuple[int, int, str]:
    return max(page, 1), min(max(page_size, 1), 100), query.strip()[:100]


@app.get("/api/files", response_model=PlatformFilePage)
def list_files(
    page: int = 1,
    page_size: int = 25,
    kind: str = "",
    query: str = "",
    latest_only: bool = False,
    include_delete_status: bool = True,
    skill_id: str = "",
    unassigned: bool = False,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> PlatformFilePage:
    checked_page, checked_page_size, checked_query = _file_list_parameters(
        page, page_size, query
    )
    if kind not in {"", "input", "output"}:
        raise HTTPException(status_code=422, detail="文件类型只能是 input 或 output。")
    checked_skill_id = skill_id.strip()[:128]
    if checked_skill_id and unassigned:
        raise HTTPException(status_code=422, detail="skill_id 和 unassigned 不能同时使用。")
    items, total = list_files_page(
        db,
        user,
        page=checked_page,
        page_size=checked_page_size,
        kind=kind,
        query=checked_query,
        latest_only=latest_only,
        include_delete_status=include_delete_status,
        skill_id=checked_skill_id,
        unassigned=unassigned,
    )
    return PlatformFilePage(
        items=items,
        total=total,
        page=checked_page,
        page_size=checked_page_size,
        pages=math.ceil(total / checked_page_size) if total else 0,
    )


@app.get("/api/files/groups", response_model=PlatformFileGroupSummaryPage)
def list_file_group_summaries(
    kind: str = "",
    query: str = "",
    latest_only: bool = True,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> PlatformFileGroupSummaryPage:
    _, _, checked_query = _file_list_parameters(1, 25, query)
    if kind not in {"", "input", "output"}:
        raise HTTPException(status_code=422, detail="文件类型只能是 input 或 output。")
    items, total_files, total_groups = list_file_groups(
        db,
        user,
        kind=kind,
        query=checked_query,
        latest_only=latest_only,
    )
    return PlatformFileGroupSummaryPage(
        items=items,
        total_files=total_files,
        total_groups=total_groups,
    )


@app.get("/api/files/selectable-inputs", response_model=PlatformFileOptionPage)
def list_selectable_input_files(
    page: int = 1,
    page_size: int = 25,
    query: str = "",
    ids: str = "",
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> PlatformFileOptionPage:
    checked_page, checked_page_size, checked_query = _file_list_parameters(
        page, page_size, query
    )
    requested_ids = [item.strip() for item in ids.split(",") if item.strip()]
    if (
        len(requested_ids) > MAX_ASSISTANT_FILE_IDS
        or any(len(item) > 128 for item in requested_ids)
    ):
        raise HTTPException(status_code=422, detail="文件标识数量或格式无效。")
    file_ids = requested_ids if ids else None
    items, total = list_selectable_input_files_page(
        db,
        user,
        page=checked_page,
        page_size=checked_page_size,
        query=checked_query,
        file_ids=file_ids,
    )
    return PlatformFileOptionPage(
        items=items,
        total=total,
        page=checked_page,
        page_size=checked_page_size,
        pages=math.ceil(total / checked_page_size) if total else 0,
    )


@app.get("/api/files/{file_id}", response_model=PlatformFileDetail)
def get_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> PlatformFileDetail:
    return get_file_detail(db, file_id, user)


@app.get("/api/files/{file_id}/download")
def download_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> FileResponse:
    record = db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在。")
    assert_owner(record.owner_id, user, "文件", record.department_id)
    path = Path(record.stored_path).resolve()
    allowed_roots = (settings.upload_dir, settings.run_dir, settings.workflow_dir)
    if not any(path.is_relative_to(root.resolve()) for root in allowed_roots):
        raise HTTPException(status_code=409, detail="文件存储路径异常，已拒绝下载。")
    if not path.is_file():
        raise HTTPException(status_code=410, detail="文件已经不存在。")
    record_audit(
        db,
        actor=user,
        action="file.download",
        resource_type="file",
        resource_id=record.id,
        details={
            "kind": record.kind,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "run_id": record.run_id or "",
        },
    )
    db.commit()
    return FileResponse(path, filename=record.original_name, media_type=record.content_type)


@app.delete("/api/files/{file_id}", status_code=204)
def remove_uploaded_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> None:
    record = db.get(FileRecord, file_id)
    if record and record.owner_id == user.user_id and record.department_id == user.department_id and record.skill_id:
        skill = registry.get(record.skill_id, include_unpublished=user.is_admin)
        if skill and skill.manifest.handler.adapter == "workflow":
            from .scheduler import acquire_claim_lock
            from .workflow_material_lock import assert_material_editable
            acquire_claim_lock(db)
            try:
                assert_material_editable(db, user, record.skill_id)
            except MaterialVersionConflict as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
    delete_upload(db, file_id, user)
    record_audit(
        db,
        actor=user,
        action="file.delete",
        resource_type="file",
        resource_id=file_id,
        details={"kind": record.kind if record else "input"},
    )
    db.commit()


@app.post("/api/runs", response_model=RunDetail)
def new_run(
    body: RunCreate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunDetail:
    run = create_run(db, body, user)
    return serialize_run(run)


@app.get("/api/workflows", response_model=list[WorkflowRead])
def workflows(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[WorkflowRead]:
    return [serialize_workflow(item) for item in list_workflows(db, user, limit, offset)]


@app.post("/api/workflows", response_model=WorkflowRead)
def new_workflow(
    body: WorkflowCreate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    return serialize_workflow(create_workflow(db, body, user))


@app.post("/api/workflows/start", response_model=WorkflowRead)
def start_workflow_session(
    body: WorkflowStart,
    response: Response,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    if body.snapshot_workflow_id:
        response.headers["Deprecation"] = "true"
        response.headers["Warning"] = (
            '299 - "snapshot_workflow_id is deprecated; use fetched_bundle_id"'
        )
    return serialize_workflow(start_workflow(db, body, user))


@app.get("/api/workflow-batches", response_model=list[WorkflowBatchRead])
def workflow_batches(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[WorkflowBatchRead]:
    batches = list_workflow_batches(db, user, limit, offset)
    runnable_skill_ids = set() if user.is_admin else allowed_skill_ids(db, user)
    return [
        serialize_workflow_batch(
            item,
            retry_authorized=user.is_admin or item.skill_id in runnable_skill_ids,
        )
        for item in batches
    ]


def _serialize_workflow_batch_for_user(db: Session, user: UserContext, batch):
    permission = None if user.is_admin else get_skill_permission(db, user.user_id, batch.skill_id)
    retry_authorized = user.is_admin or bool(permission and permission.can_run)
    return serialize_workflow_batch(batch, retry_authorized=retry_authorized)


@app.post("/api/workflow-batches/start", response_model=WorkflowBatchRead)
def start_workflow_batch_session(
    body: WorkflowBatchStart,
    response: Response,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowBatchRead:
    if body.snapshot_workflow_id:
        response.headers["Deprecation"] = "true"
        response.headers["Warning"] = (
            '299 - "snapshot_workflow_id is deprecated; use fetched_bundle_id"'
        )
    return _serialize_workflow_batch_for_user(db, user, start_workflow_batch(db, body, user))


@app.get("/api/workflow-batches/{batch_id}", response_model=WorkflowBatchRead)
def get_workflow_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowBatchRead:
    return _serialize_workflow_batch_for_user(
        db, user, get_workflow_batch_or_404(db, batch_id, user)
    )


@app.post("/api/workflow-batches/{batch_id}/retry", response_model=WorkflowBatchRead)
def retry_workflow_batch_session(
    batch_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowBatchRead:
    batch = get_workflow_batch_or_404(db, batch_id, user)
    assert_skill_permission(db, user, batch.skill_id)
    return _serialize_workflow_batch_for_user(db, user, retry_workflow_batch(db, batch, user))


@app.post("/api/workflow-batches/{batch_id}/cancel", response_model=WorkflowBatchRead)
def cancel_workflow_batch_session(
    batch_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowBatchRead:
    return _serialize_workflow_batch_for_user(db, user, cancel_workflow_batch(db, batch_id, user))


@app.get(
    "/api/workflow-batches/{batch_id}/fetched-data",
    response_model=WorkflowFetchedDataRead,
)
def get_workflow_batch_fetched_data(
    batch_id: str,
    reconciliation_date: str,
    dataset: str = "ar_groups",
    offset: int = 0,
    limit: int = 100,
    query: str = "",
    issues_only: bool = False,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowFetchedDataRead:
    batch = get_workflow_batch_or_404(db, batch_id, user)
    assert_skill_permission(db, user, batch.skill_id)
    result = read_batch_fetched_data(
        batch, reconciliation_date, dataset, offset, limit, query, issues_only, db=db
    )
    db.commit()
    return result


@app.post(
    "/api/workflow-batches/{batch_id}/fetched-data/confirm",
    response_model=WorkflowBatchRead,
)
def confirm_workflow_batch_fetched_data(
    batch_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowBatchRead:
    batch = get_workflow_batch_or_404(db, batch_id, user)
    assert_skill_permission(db, user, batch.skill_id)
    confirmed = confirm_batch_fetched_data_review(db, batch, user)
    record_audit(
        db,
        actor=user,
        action="workflow_batch.fetched_data.confirm",
        resource_type="workflow_batch",
        resource_id=batch.id,
        details={"skill_id": batch.skill_id},
    )
    db.commit()
    return _serialize_workflow_batch_for_user(db, user, confirmed)


@app.post(
    "/api/workflow-batches/{batch_id}/fetched-data/supplement",
    response_model=WorkflowBatchRead,
)
def supplement_workflow_batch_fetched_data(
    batch_id: str,
    body: WorkflowBatchFetchedDataSupplement,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowBatchRead:
    batch = get_workflow_batch_or_404(db, batch_id, user)
    assert_skill_permission(db, user, batch.skill_id)
    requested, supplement = request_batch_fetched_data_supplement(
        db,
        batch,
        body.reconciliation_date,
        body.ar_ids,
        body.so_ids,
    )
    record_audit(
        db,
        actor=user,
        action="workflow_batch.fetched_data.supplement.requested",
        resource_type="workflow_batch",
        resource_id=batch.id,
        details={
            "skill_id": batch.skill_id,
            "reconciliation_date": body.reconciliation_date,
            "requested": supplement_audit_summary(supplement),
        },
    )
    db.commit()
    return _serialize_workflow_batch_for_user(db, user, requested)


@app.post("/api/workflows/{workflow_id}/cancel", response_model=WorkflowRead)
def cancel_workflow_session(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    return serialize_workflow(cancel_workflow(db, workflow_id, user))


@app.get("/api/workflows/material-edit-state")
def get_material_edit_state(
    skill_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> dict:
    from .workflow_material_lock import material_edit_state
    assert_skill_permission(db, user, skill_id)
    return material_edit_state(db, user, skill_id)


@app.delete("/api/workflows/reusable-files")
def remove_reusable_workflow_files(
    skill_id: str,
    file_id: str | None = None,
    all_files: bool = False,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> dict[str, int]:
    from .ar_material_candidates import remove_material_candidates
    from .authorization import refresh_active_user
    from .scheduler import acquire_claim_lock
    assert_skill_permission(db, user, skill_id)
    acquire_claim_lock(db)
    user = refresh_active_user(db, user)
    assert_skill_permission(db, user, skill_id)
    count = remove_material_candidates(db, user, skill_id, file_id=file_id, all_files=all_files)
    db.commit()
    return {"removed_count": count}


@app.get("/api/workflows/reusable-files", response_model=WorkflowReusableFilesRead)
def get_reusable_workflow_files(
    skill_id: str,
    candidate_page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowReusableFilesRead:
    files, missing_roles, material = reusable_workflow_files(db, skill_id, user, include_candidates=True, candidate_page=candidate_page)
    return WorkflowReusableFilesRead(
        skill_id=skill_id,
        files=files,
        ready=not missing_roles,
        missing_roles=missing_roles,
        **material,
    )


@app.get(
    "/api/workflows/fetched-snapshots",
    response_model=list[WorkflowFetchedSnapshotRead],
)
def get_fetched_snapshot_options(
    skill_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[WorkflowFetchedSnapshotRead]:
    return list_fetched_snapshot_options(db, skill_id, user)


@app.get("/api/workflows/material-sets", response_model=list[WorkflowMaterialSetRead])
def get_workflow_material_sets(
    skill_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[WorkflowMaterialSetRead]:
    assert_skill_permission(db, user, skill_id)
    return [
        WorkflowMaterialSetRead(**serialize_material_set(db, item))
        for item in list_material_sets(db, user, skill_id, limit=limit)
    ]


@app.post(
    "/api/workflows/material-sets/{material_set_id}/restore",
    response_model=WorkflowMaterialSetRead,
)
def restore_workflow_material_set(
    material_set_id: str,
    skill_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowMaterialSetRead:
    assert_skill_permission(db, user, skill_id, "can_upload")
    try:
        restored = restore_material_set(db, user, skill_id, material_set_id)
    except MaterialVersionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit(
        db,
        actor=user,
        action="workflow.material_set.restore",
        resource_type="workflow_material_set",
        resource_id=restored.id,
        details={
            "skill_id": skill_id,
            "restored_from_material_set_id": material_set_id,
            "new_version": restored.version,
        },
    )
    db.commit()
    return WorkflowMaterialSetRead(**serialize_material_set(db, restored))


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    return serialize_workflow(get_workflow_or_404(db, workflow_id, user))


@app.get("/api/workflows/{workflow_id}/execution", response_model=ArExecutionRead)
def get_workflow_execution(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ArExecutionRead:
    return read_execution(get_workflow_or_404(db, workflow_id, user))


@app.post("/api/workflows/{workflow_id}/execution/recover", response_model=ArExecutionRead)
def recover_workflow_execution(
    workflow_id: str,
    body: ArRecoveryRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ArExecutionRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    recover_execution(db, workflow, body, user)
    db.expire(workflow, ["actions"])
    return read_execution(workflow)


@app.post("/api/workflows/{workflow_id}/execution/investigate", response_model=ArExecutionRead)
def investigate_failed_workflow_write(
    workflow_id: str,
    body: ArRecoveryRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ArExecutionRead:
    from .ar_business_investigation import queue_investigation

    workflow = get_workflow_or_404(db, workflow_id, user)
    queue_investigation(db, workflow, body, user)
    db.expire(workflow, ["actions"])
    return read_execution(workflow)


@app.get("/api/workflows/{workflow_id}/result-details", response_model=ArResultPage)
def get_workflow_result_details(
    workflow_id: str,
    category: str = Query("all", pattern="^(all|written|skipped|hold|conflict|exception)$"),
    offset: int = Query(0, ge=0), limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db), user: UserContext = Depends(get_current_user),
) -> ArResultPage:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    return read_result_page(db, [workflow], category=category, offset=offset, limit=limit)


@app.get("/api/workflow-batches/{batch_id}/result-details", response_model=ArResultPage)
def get_batch_result_details(
    batch_id: str,
    category: str = Query("all", pattern="^(all|written|skipped|hold|conflict|exception)$"),
    offset: int = Query(0, ge=0), limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db), user: UserContext = Depends(get_current_user),
) -> ArResultPage:
    batch = get_workflow_batch_or_404(db, batch_id, user)
    assert_skill_permission(db, user, batch.skill_id)
    from .resource_policy import assert_owner
    for workflow in batch.workflows:
        assert_owner(workflow.owner_id, user, "核销任务", workflow.department_id)
        assert_skill_permission(db, user, workflow.skill_id)
    return read_result_page(db, list(batch.workflows), category=category, offset=offset, limit=limit)


@app.get("/api/workflows/{workflow_id}/order-evidence", response_model=ArEvidencePage)
def get_workflow_order_evidence(
    workflow_id: str,
    offset: int = 0,
    limit: int = 20,
    query: str = "",
    record_id: str = "",
    detail_offset: int = 0,
    fingerprint: str = "",
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ArEvidencePage:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    return read_evidence_page(db, workflow, offset=offset, limit=limit, query=query, record_id=record_id,
                              detail_offset=detail_offset, fingerprint=fingerprint)


@app.get("/api/workflows/{workflow_id}/fetched-data", response_model=WorkflowFetchedDataRead)
def get_workflow_fetched_data(
    workflow_id: str,
    dataset: str = "ar_groups",
    offset: int = 0,
    limit: int = 100,
    query: str = "",
    issues_only: bool = False,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowFetchedDataRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    result = read_workflow_fetched_data(
        workflow, dataset, offset, limit, query=query, issues_only=issues_only, db=db
    )
    db.commit()
    return result


@app.post("/api/workflows/{workflow_id}/fetched-data/confirm", response_model=WorkflowRead)
def confirm_workflow_fetched_data(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    confirmed = confirm_fetched_data_review(db, workflow, user)
    record_audit(
        db,
        actor=user,
        action="workflow.fetched_data.confirm",
        resource_type="workflow",
        resource_id=workflow.id,
        details={
            "skill_id": workflow.skill_id,
            "reconciliation_date": workflow.reconciliation_date,
        },
    )
    db.commit()
    return serialize_workflow(confirmed)


@app.post("/api/workflows/{workflow_id}/fetched-data/supplement", response_model=WorkflowRead)
def supplement_workflow_fetched_data(
    workflow_id: str,
    body: WorkflowFetchedDataSupplement,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    requested, supplement = request_fetched_data_supplement(
        db,
        workflow,
        body.ar_ids,
        body.so_ids,
    )
    record_audit(
        db,
        actor=user,
        action="workflow.fetched_data.supplement",
        resource_type="workflow",
        resource_id=workflow.id,
        details={
            "skill_id": workflow.skill_id,
            **supplement_audit_summary(supplement),
        },
    )
    db.commit()
    return serialize_workflow(requested)


@app.post(
    "/api/workflows/{workflow_id}/agent/actions",
    response_model=WorkflowAgentActionResponse,
)
def workflow_agent_action(
    workflow_id: str,
    body: WorkflowAgentActionRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowAgentActionResponse:
    """Apply one allowlisted Agent request; scripts remain Worker-owned."""
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    result = apply_workflow_agent_action(
        db,
        workflow,
        body.action,
        body.arguments.model_dump(),
        user,
    )
    return WorkflowAgentActionResponse(
        workflow=serialize_workflow(result.workflow),
        action=result.action,
        await_confirmation=result.await_confirmation,
        confirmation_kind=result.confirmation_kind,
        message=result.message,
    )


@app.get(
    "/api/workflows/{workflow_id}/agent/context",
    response_model=WorkflowAgentContext,
)
def workflow_agent_context(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowAgentContext:
    """Return server-only model binding data without adding it to the public workflow DTO."""
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    return WorkflowAgentContext(
        workflow=serialize_workflow(workflow),
        connection_id=(
            None
            if is_background_model_connection(workflow.model_connection_id)
            else workflow.model_connection_id
        ),
        model=(
            ""
            if is_background_model_connection(workflow.model_connection_id)
            else workflow.model_name
        ),
    )


@app.put("/api/workflows/{workflow_id}/files", response_model=WorkflowRead)
def set_workflow_files(
    workflow_id: str,
    body: WorkflowFilesUpdate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id, "can_upload")
    return serialize_workflow(
        update_workflow_files(db, workflow, body.files, user, body.replace_roles)
    )


@app.post("/api/workflows/{workflow_id}/messages", response_model=WorkflowRead)
def workflow_message(
    workflow_id: str,
    body: WorkflowMessageCreate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    if is_explicit_workflow_cancel_request(body.content):
        if workflow.batch_id:
            batch = cancel_workflow_batch(db, workflow.batch_id, user)
            current = next(item for item in batch.workflows if item.id == workflow.id)
            return serialize_workflow(current)
        return serialize_workflow(cancel_workflow(db, workflow.id, user))
    assert_skill_permission(db, user, workflow.skill_id)
    return serialize_workflow(send_workflow_message(db, workflow, body.content, user))


@app.post("/api/workflows/{workflow_id}/confirm", response_model=WorkflowRead)
def confirm_workflow_result(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    return serialize_workflow(
        send_workflow_message(db, workflow, "我已检查核销日清，确认写入", user)
    )


@app.post("/api/workflows/{workflow_id}/rebuild", response_model=WorkflowRead)
def rebuild_workflow_result(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    assert_skill_permission(db, user, workflow.skill_id)
    rebuilt = rebuild_failed_workflow(db, workflow, user)
    db.commit()
    db.refresh(rebuilt)
    return serialize_workflow(rebuilt)


@app.post("/api/workflows/{workflow_id}/reset", response_model=WorkflowRead)
def reset_workflow_session(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    return serialize_workflow(reset_workflow(db, workflow, user))


@app.get("/api/workbench", response_model=Workbench)
def workbench(
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> Workbench:
    return get_workbench(db, user)


@app.get("/api/runs", response_model=RunPage)
def list_runs(
    page: int = 1,
    page_size: int = 20,
    state: str = "",
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunPage:
    checked_page = max(page, 1)
    checked_page_size = min(max(page_size, 1), 100)
    items, total = list_runs_page(
        db,
        user,
        page=checked_page,
        page_size=checked_page_size,
        state=state.strip()[:40],
    )
    return RunPage(
        items=items,
        total=total,
        page=checked_page,
        page_size=checked_page_size,
        pages=math.ceil(total / checked_page_size) if total else 0,
    )


@app.get("/api/task-center", response_model=TaskCenterPage)
def list_task_center_items(
    page: int = 1,
    page_size: int = 20,
    query: str = "",
    view_state: TaskCenterViewState | None = None,
    item_type: TaskCenterReferenceType | None = None,
    skill_id: str = "",
    business_date_from: str = "",
    business_date_to: str = "",
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> TaskCenterPage:
    return query_task_center(
        db,
        user,
        page=max(page, 1),
        page_size=min(max(page_size, 1), 100),
        query=query.strip()[:128],
        view_state=view_state,
        item_type=item_type,
        skill_id=skill_id.strip()[:128],
        business_date_from=business_date_from.strip(),
        business_date_to=business_date_to.strip(),
        updated_from=updated_from,
        updated_to=updated_to,
    )


@app.get("/api/runs/{run_id}", response_model=RunDetail)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunDetail:
    stored = get_run_or_404(db, run_id, user)
    can_retry, reason = retry_status(db, stored, user)
    return serialize_run(stored, can_retry=can_retry, retry_block_reason=reason)


@app.get("/api/runs/{run_id}/steps", response_model=list[StepRunRead])
def get_run_steps(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[StepRunRead]:
    return list_run_steps(db, run_id, user)


@app.get("/api/runs/{run_id}/approvals", response_model=list[RunApprovalRead])
def get_run_approvals(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[RunApprovalRead]:
    return list_run_approvals(db, run_id, user)


@app.get("/api/runs/{run_id}/event-history", response_model=list[RunEventRead])
def get_run_event_history(
    run_id: str,
    offset: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[RunEventRead]:
    get_run_or_404(db, run_id, user)
    rows = db.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run_id)
        .order_by(RunEvent.id.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 200))
    ).all()
    return [
        RunEventRead(
            id=item.id,
            type=item.event_type,
            state=item.state,
            progress=item.progress,
            message=sanitize_text(item.message, error=item.state in {"failed", "timed_out"}),
            data=sanitize_value(json.loads(item.data_json or "{}")),
            created_at=item.created_at,
        )
        for item in rows
    ]


@app.post("/api/runs/{run_id}/retry", response_model=RunDetail)
def retry(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunDetail:
    source = get_run_or_404(db, run_id, user)
    retried = retry_run(db, source, user)
    record_audit(
        db,
        actor=user,
        action="run.retry",
        resource_type="run",
        resource_id=retried.id,
        details={"source_run_id": source.id, "skill_id": source.skill_id},
    )
    db.commit()
    return serialize_run(retried)


@app.post("/api/runs/{run_id}/confirm", response_model=RunActionResponse)
def confirm(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunActionResponse:
    stored = get_run_or_404(db, run_id, user)
    assert_skill_permission(db, user, stored.skill_id)
    run = confirm_run(db, stored, user)
    return RunActionResponse(id=run.id, state=run.state, message="任务已确认。")


@app.post("/api/runs/{run_id}/cancel", response_model=RunActionResponse)
def cancel(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunActionResponse:
    run = cancel_run(db, get_run_or_404(db, run_id, user))
    return RunActionResponse(id=run.id, state=run.state, message="取消请求已提交。")


@app.get(
    "/api/runs/{run_id}/events",
    responses={
        200: {
            "description": "RunEventRead 的 Server-Sent Events 数据流。",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def run_events(
    run_id: str,
    after: int = 0,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_sse_user),
) -> StreamingResponse:
    get_run_or_404(db, run_id, user)

    async def stream():
        last_id = after
        idle = 0
        while True:
            with SessionLocal() as event_db:
                events = event_db.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                    .order_by(RunEvent.id.asc())
                ).all()
                for event in events:
                    last_id = event.id
                    data = {
                        "id": event.id,
                        "type": event.event_type,
                        "state": event.state,
                        "progress": event.progress,
                        "message": sanitize_text(
                            event.message,
                            error=event.state in {"failed", "timed_out"},
                        ),
                        "data": sanitize_value(json.loads(event.data_json or "{}")),
                        "created_at": event.created_at.isoformat(),
                    }
                    payload = json.dumps(data, ensure_ascii=False)
                    yield (f"id: {event.id}\nevent: {event.event_type}\ndata: {payload}\n\n")
                    idle = 0
                run = event_db.get(RunRecord, run_id)
                if run and run.state in TERMINAL_STATES and not events:
                    break
            idle += 1
            if idle % 15 == 0:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/admin/registry/reload", response_model=RegistryReloadResponse)
def reload_registry(
    user: UserContext = Depends(get_current_user),
) -> RegistryReloadResponse:
    require_admin(user)
    registry.refresh()
    return RegistryReloadResponse(
        skills=len(registry.list(include_disabled=True)),
        errors=registry.errors,
    )


@app.exception_handler(ValueError)
async def value_error_handler(_, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/docs", include_in_schema=False)
def docs_ui(user: UserContext = Depends(get_current_user)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{settings.app_name} API")


@app.get("/redoc", include_in_schema=False)
def redoc_ui(user: UserContext = Depends(get_current_user)):
    return get_redoc_html(openapi_url="/openapi.json", title=f"{settings.app_name} API")


@app.get("/openapi.json", include_in_schema=False)
def openapi_json(user: UserContext = Depends(get_current_user)):
    return JSONResponse(app.openapi())


if settings.frontend_dist.exists():
    assets = settings.frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        dist_root = settings.frontend_dist.resolve()
        target = (dist_root / path).resolve()
        if path and target.is_relative_to(dist_root) and target.is_file():
            return FileResponse(target)
        return FileResponse(dist_root / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def api_root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "message": "前端尚未构建；开发模式请访问 http://localhost:5173",
            "docs": "/docs",
        }
