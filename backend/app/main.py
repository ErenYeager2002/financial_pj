from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext, get_current_user, get_sse_user, require_admin
from .database import SessionLocal, get_db, init_db
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
from .registry import registry
from .run_service import (
    TERMINAL_STATES,
    cancel_run,
    confirm_run,
    create_run,
    get_run_or_404,
    serialize_run,
)
from .schemas import (
    InterpretRequest,
    InterpretResponse,
    ModelConnectionRead,
    ModelConnectRequest,
    ModelSelectRequest,
    RunActionResponse,
    RunCreate,
    RunRead,
    ServiceCredentialRead,
    ServiceCredentialWrite,
    WorkflowCreate,
    WorkflowFilesUpdate,
    WorkflowMessageCreate,
    WorkflowRead,
)
from .service_credential_service import (
    get_service_credential_status,
    remove_service_credential,
    save_service_credential,
)
from .settings import settings
from .storage import save_upload
from .workflow_service import (
    create_workflow,
    get_workflow_or_404,
    list_workflows,
    send_workflow_message,
    serialize_workflow,
    update_workflow_files,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    init_db()
    registry.refresh()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "name": settings.app_name,
        "environment": settings.environment,
        "skills": len(registry.list(include_disabled=True)),
        "registry_errors": registry.errors,
    }


@app.get("/api/session")
def session(user: UserContext = Depends(get_current_user)) -> dict[str, str]:
    return {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "role": user.role,
        "department_id": user.department_id,
    }


@app.get("/api/skills")
def list_skills(
    user: UserContext = Depends(get_current_user),
) -> list[dict[str, object]]:
    return [
        item.public_dict(include_schema=True)
        for item in registry.list(include_disabled=user.is_admin)
    ]


@app.get("/api/skills/{skill_id}")
def get_skill(
    skill_id: str,
    user: UserContext = Depends(get_current_user),
) -> dict[str, object]:
    skill = registry.get(skill_id, include_unpublished=user.is_admin)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在。")
    return skill.public_dict(include_schema=True)


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


@app.post("/api/model-connections", response_model=ModelConnectionRead)
def connect_model(
    body: ModelConnectRequest,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ModelConnectionRead:
    return connect_api_key(db, user, body.api_key)


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


@app.post("/api/files")
async def upload_file(
    upload: UploadFile = File(...),
    role: str = Form(default=""),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> dict[str, object]:
    record = await save_upload(db, upload, user)
    return {
        "id": record.id,
        "name": record.original_name,
        "role": role,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "kind": record.kind,
    }


@app.get("/api/files/{file_id}/download")
def download_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> FileResponse:
    record = db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在。")
    if record.department_id != user.department_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权下载其他部门文件。")
    path = Path(record.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="文件已经不存在。")
    return FileResponse(path, filename=record.original_name, media_type=record.content_type)


@app.post("/api/runs", response_model=RunRead)
def new_run(
    body: RunCreate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunRead:
    run = create_run(db, body, user)
    return serialize_run(run)


@app.get("/api/workflows", response_model=list[WorkflowRead])
def workflows(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[WorkflowRead]:
    return [serialize_workflow(item) for item in list_workflows(db, user, limit)]


@app.post("/api/workflows", response_model=WorkflowRead)
def new_workflow(
    body: WorkflowCreate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    return serialize_workflow(create_workflow(db, body, user))


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    return serialize_workflow(get_workflow_or_404(db, workflow_id, user))


@app.put("/api/workflows/{workflow_id}/files", response_model=WorkflowRead)
def set_workflow_files(
    workflow_id: str,
    body: WorkflowFilesUpdate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    return serialize_workflow(update_workflow_files(db, workflow, body.files, user))


@app.post("/api/workflows/{workflow_id}/messages", response_model=WorkflowRead)
def workflow_message(
    workflow_id: str,
    body: WorkflowMessageCreate,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> WorkflowRead:
    workflow = get_workflow_or_404(db, workflow_id, user)
    return serialize_workflow(send_workflow_message(db, workflow, body.content, user))


@app.get("/api/runs", response_model=list[RunRead])
def list_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[RunRead]:
    query = (
        select(RunRecord)
        .where(RunRecord.department_id == user.department_id)
        .order_by(RunRecord.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return [serialize_run(item) for item in db.scalars(query).all()]


@app.get("/api/runs/{run_id}", response_model=RunRead)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunRead:
    return serialize_run(get_run_or_404(db, run_id, user))


@app.post("/api/runs/{run_id}/confirm", response_model=RunActionResponse)
def confirm(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunActionResponse:
    run = confirm_run(db, get_run_or_404(db, run_id, user), user)
    return RunActionResponse(id=run.id, state=run.state, message="任务已确认。")


@app.post("/api/runs/{run_id}/cancel", response_model=RunActionResponse)
def cancel(
    run_id: str,
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> RunActionResponse:
    run = cancel_run(db, get_run_or_404(db, run_id, user))
    return RunActionResponse(id=run.id, state=run.state, message="取消请求已提交。")


@app.get("/api/runs/{run_id}/events")
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
                        "message": event.message,
                        "data": json.loads(event.data_json or "{}"),
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


@app.post("/api/admin/registry/reload")
def reload_registry(
    user: UserContext = Depends(get_current_user),
) -> dict[str, object]:
    require_admin(user)
    registry.refresh()
    return {
        "skills": len(registry.list(include_disabled=True)),
        "errors": registry.errors,
    }


@app.exception_handler(ValueError)
async def value_error_handler(_, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


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
