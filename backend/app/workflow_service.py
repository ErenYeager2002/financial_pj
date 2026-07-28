from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .auth import UserContext
from .model_service import resolve_runtime_config
from .models import FileRecord, WorkflowAction, WorkflowMessage, WorkflowSession
from .registry import RegisteredSkill, registry
from .schemas import WorkflowCreate, WorkflowRead
from .service_credential_service import (
    has_service_credential,
    resolve_service_credential,
)
from .settings import settings
from .storage import safe_filename, sha256_file
from .workflow_orchestrator import WorkflowDecision, decide_workflow_turn

WEEKDAYS = "一二三四五六日"
CONFIRM_STAGES = {"awaiting_date_confirmation", "awaiting_apply_confirmation"}
BUSY_STAGES = {"preparing", "applying"}
FILE_ROLES = {
    "finance_workbooks": "02_我的表副本",
}
CONFIRM_REPLIES = {"确认", "可以", "可以写", "按这个写", "没问题写吧", "写吧", "对", "是"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _assert_visible(workflow: WorkflowSession, user: UserContext) -> None:
    if workflow.department_id != user.department_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权查看其他部门的对话任务。")


def get_workflow_or_404(
    db: Session,
    workflow_id: str,
    user: UserContext,
) -> WorkflowSession:
    workflow = db.get(WorkflowSession, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="对话任务不存在。")
    _assert_visible(workflow, user)
    return workflow


def _message(
    db: Session,
    workflow: WorkflowSession,
    role: str,
    content: str,
    data: dict[str, Any] | None = None,
) -> WorkflowMessage:
    item = WorkflowMessage(
        workflow_id=workflow.id,
        role=role,
        content=content,
        data_json=_json(data or {}),
    )
    db.add(item)
    workflow.updated_at = datetime.now(UTC)
    return item


def serialize_workflow(workflow: WorkflowSession) -> WorkflowRead:
    messages = sorted(workflow.messages, key=lambda item: item.id)
    actions = sorted(workflow.actions, key=lambda item: item.queued_at)
    return WorkflowRead(
        id=workflow.id,
        owner_id=workflow.owner_id,
        skill_id=workflow.skill_id,
        skill_name=workflow.skill_name,
        skill_version=workflow.skill_version,
        model_provider=workflow.model_provider,
        model_name=workflow.model_name,
        state=workflow.state,
        stage=workflow.stage,
        reconciliation_date=workflow.reconciliation_date,
        progress=workflow.progress,
        progress_message=workflow.progress_message,
        error_message=workflow.error_message,
        files=_load(workflow.files_json, {}),
        artifacts=_load(workflow.artifacts_json, []),
        messages=[
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "data": _load(item.data_json, {}),
                "created_at": item.created_at,
            }
            for item in messages
        ],
        actions=[
            {
                "id": item.id,
                "name": item.name,
                "state": item.state,
                "error_message": item.error_message,
                "created_at": item.queued_at,
                "finished_at": item.finished_at,
            }
            for item in actions
        ],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _snapshot_skill(skill: RegisteredSkill, workflow_id: str) -> Path:
    root = (settings.workflow_dir / workflow_id).resolve()
    destination = root / "skill"
    root.mkdir(parents=True, exist_ok=False)
    for path in skill.directory.rglob("*"):
        if path.is_symlink():
            raise HTTPException(status_code=422, detail="Skill 包不能包含符号链接。")
    shutil.copytree(
        skill.directory,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", ".ruff_cache", "工作区", "output"
        ),
    )
    return destination


def create_workflow(
    db: Session,
    request: WorkflowCreate,
    user: UserContext,
) -> WorkflowSession:
    skill = registry.get(request.skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="对话式 Skill 不存在或尚未发布。")
    llm = resolve_runtime_config(db, user, request.model_connection_id, request.model)
    if not llm:
        raise HTTPException(status_code=422, detail="对话式 Skill 必须选择一个大模型连接。")
    workflow_id = str(uuid.uuid4())
    _snapshot_skill(skill, workflow_id)
    workflow = WorkflowSession(
        id=workflow_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_hash=skill.skill_hash,
        skill_commit=skill.commit_sha,
        model_connection_id=llm.connection_id,
        model_provider=llm.provider,
        model_name=llm.model,
        state="active",
        stage="awaiting_date",
        progress_message="等待确认核销日期",
    )
    db.add(workflow)
    _message(
        db,
        workflow,
        "assistant",
        "先告诉我要跑的核销日期。可以说“昨天”或直接说“2026-07-24”。",
        {"kind": "date_request"},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def list_workflows(db: Session, user: UserContext, limit: int = 50) -> list[WorkflowSession]:
    query = (
        select(WorkflowSession)
        .where(WorkflowSession.department_id == user.department_id)
        .order_by(WorkflowSession.updated_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return list(db.scalars(query).all())


def update_workflow_files(
    db: Session,
    workflow: WorkflowSession,
    bindings: dict[str, list[str]],
    user: UserContext,
) -> WorkflowSession:
    editable_stages = {
        "awaiting_date",
        "awaiting_date_confirmation",
        "awaiting_files",
        "failed",
    }
    if workflow.stage not in editable_stages:
        raise HTTPException(status_code=409, detail="当前阶段不能更换输入文件。")
    skill = registry.get(workflow.skill_id)
    if not skill:
        raise HTTPException(status_code=409, detail="Skill 当前不可用。")
    specs = {item.role: item for item in skill.manifest.file_inputs}
    unknown = set(bindings) - set(specs)
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知文件角色：{sorted(unknown)}")
    normalized = _load(workflow.files_json, {})
    for role, ids in bindings.items():
        spec = specs[role]
        if not spec.multiple and len(ids) > 1:
            raise HTTPException(status_code=422, detail=f"{spec.name}只能上传一个文件。")
        if ids and len(ids) < spec.min_files:
            raise HTTPException(
                status_code=422,
                detail=f"{spec.name}至少需要 {spec.min_files} 个文件。",
            )
        records: list[dict[str, Any]] = []
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            if not record or record.kind != "input":
                raise HTTPException(status_code=422, detail=f"输入文件不存在：{file_id}")
            if record.department_id != user.department_id and not user.is_admin:
                raise HTTPException(status_code=403, detail="无权使用其他部门文件。")
            suffix = Path(record.original_name).suffix.lower().lstrip(".")
            allowed = [item.lower().lstrip(".") for item in spec.extensions]
            if allowed and suffix not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=f"{spec.name}不支持 .{suffix}，允许：{', '.join(allowed)}",
                )
            records.append(
                {
                    "file_id": record.id,
                    "name": record.original_name,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                }
            )
        normalized[role] = records
    workflow.files_json = _json(normalized)
    workflow.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(workflow)
    return workflow


def _parse_date(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed <= date.today() else None


def _date_label(value: str) -> str:
    parsed = _parse_date(value)
    if not parsed:
        return "未确认"
    return f"{value}（周{WEEKDAYS[parsed.weekday()]}）"


def _has_required_files(workflow: WorkflowSession) -> tuple[bool, list[str]]:
    files = _load(workflow.files_json, {})
    skill = registry.get(workflow.skill_id)
    if not skill:
        return False, list(FILE_ROLES)
    missing = [
        spec.role
        for spec in skill.manifest.file_inputs
        if spec.required and len(files.get(spec.role, [])) < spec.min_files
    ]
    return not missing, missing


def _queue_action(
    db: Session,
    workflow: WorkflowSession,
    name: str,
) -> WorkflowAction:
    pending = db.scalar(
        select(WorkflowAction.id).where(
            WorkflowAction.workflow_id == workflow.id,
            WorkflowAction.state.in_(("queued", "running")),
        )
    )
    if pending:
        raise HTTPException(status_code=409, detail="当前已有动作正在执行。")
    action = WorkflowAction(
        id=str(uuid.uuid4()),
        workflow_id=workflow.id,
        name=name,
        input_json=_json(
            {
                "reconciliation_date": workflow.reconciliation_date,
                "files": _load(workflow.files_json, {}),
                "context": _load(workflow.context_json, {}),
            }
        ),
    )
    db.add(action)
    return action


def _status_reply(workflow: WorkflowSession) -> str:
    if workflow.stage == "awaiting_date_confirmation":
        return f"当前核销日期是 {_date_label(workflow.reconciliation_date)}，请回复“确认”。"
    if workflow.stage == "preparing":
        return f"正在生成 {_date_label(workflow.reconciliation_date)} 的《核销日清》。"
    labels = {
        "awaiting_date": "请先告诉我核销日期。",
        "awaiting_files": (
            "请安全保存智云账号，并上传盈亏表和到账流转表副本，"
            "传好后回复“上传好了”。智云核销数据由平台自动获取。"
        ),
        "awaiting_apply_confirmation": "《核销日清》已生成；请打开检查，确认后回复“确认”。",
        "applying": "正在执行确认后的写入和回读校验，请不要修改相关表格。",
        "completed": "本次核销已完成，结果文件可以下载。",
        "failed": "上一步没有完成。请根据错误提示补齐材料后回复“重出日清”。",
        "cancelled": "本次对话任务已经取消。",
    }
    return labels.get(workflow.stage, workflow.progress_message or "正在处理。")


def _is_explicit_confirmation(content: str, *, apply: bool) -> bool:
    normalized = content.lower().replace(" ", "").strip("。！!，,")
    if normalized in CONFIRM_REPLIES:
        return True
    if apply:
        return normalized in {
            "确认写入",
            "确认回填",
            "可以写入",
            "同意写入",
            "我已检查核销日清，确认写入",
        }
    return normalized in {"确认日期", "日期确认"}


def _apply_decision(
    db: Session,
    workflow: WorkflowSession,
    decision: WorkflowDecision,
) -> None:
    action = decision.action
    source = {"decision_source": decision.source, "action": action}
    if action == "reply":
        content = str(decision.arguments.get("content", "")).strip()
        _message(
            db,
            workflow,
            "assistant",
            content[:8000] if content else _status_reply(workflow),
            source,
        )
        return
    if action == "set_date":
        value = str(decision.arguments.get("date", ""))
        parsed = _parse_date(value)
        if not parsed:
            _message(
                db,
                workflow,
                "assistant",
                "这个日期无法使用。请给出不晚于今天的有效核销日期，例如 2026-07-24。",
                source,
            )
            return
        workflow.reconciliation_date = parsed.isoformat()
        workflow.stage = "awaiting_date_confirmation"
        workflow.state = "active"
        workflow.progress_message = "等待确认核销日期"
        _message(
            db,
            workflow,
            "assistant",
            f"我按核销日期 {_date_label(workflow.reconciliation_date)} 来跑——"
            "就是销售在这一天核销的到账，对吗？请回复“确认”，日期不对就直接告诉我新日期。",
            source,
        )
        return
    if action == "confirm_date":
        if workflow.stage != "awaiting_date_confirmation" or not workflow.reconciliation_date:
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        workflow.stage = "awaiting_files"
        workflow.state = "active"
        workflow.progress_message = "等待智云凭据和财务工作簿"
        _message(
            db,
            workflow,
            "assistant",
            "日期已确认。请在右侧安全保存智云账号，并上传盈亏表和到账流转表副本。"
            "智云回款、核销和订单数据会自动获取；准备好后回复“上传好了”。",
            source,
        )
        return
    if action == "prepare_worklist":
        if workflow.stage not in {"awaiting_files", "failed"}:
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        ready, missing = _has_required_files(workflow)
        if not ready:
            labels = {"finance_workbooks": "盈亏/流转表副本"}
            _message(
                db,
                workflow,
                "assistant",
                "还缺：" + "、".join(labels[item] for item in missing) + "。上传后再说“上传好了”。",
                source,
            )
            return
        if not has_service_credential(
            db,
            workflow.owner_id,
            workflow.department_id,
            "zhiyun",
        ):
            _message(
                db,
                workflow,
                "assistant",
                "还缺智云账号。请先在右侧“智云自动取数”中安全保存账号和密码，"
                "再回复“上传好了”。",
                source,
            )
            return
        _queue_action(db, workflow, "prepare_worklist")
        workflow.context_json = "{}"
        workflow.artifacts_json = "[]"
        workflow.stage = "preparing"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "已排队，准备生成核销日清"
        workflow.error_message = ""
        _message(
            db,
            workflow,
            "assistant",
            f"材料已收到，开始生成 {_date_label(workflow.reconciliation_date)} 的《核销日清》。"
            "在我明确说清单已生成前，不会写盈亏表或流转表。",
            source,
        )
        return
    if action == "confirm_apply":
        if workflow.stage != "awaiting_apply_confirmation":
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        _queue_action(db, workflow, "apply_confirmed")
        workflow.stage = "applying"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "已确认，等待执行写入"
        workflow.error_message = ""
        _message(
            db,
            workflow,
            "assistant",
            "已收到写入确认。现在执行：先写盈亏明细，再写流转安全子集，随后回读校验。",
            source,
        )
        return
    if action == "rebuild_worklist":
        if workflow.stage in BUSY_STAGES:
            _message(db, workflow, "assistant", "当前动作还在执行，完成后才能重出清单。", source)
            return
        ready, _ = _has_required_files(workflow)
        has_credential = has_service_credential(
            db,
            workflow.owner_id,
            workflow.department_id,
            "zhiyun",
        )
        if not ready or not has_credential or not workflow.reconciliation_date:
            workflow.stage = "awaiting_files" if workflow.reconciliation_date else "awaiting_date"
            workflow.state = "active"
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        _queue_action(db, workflow, "prepare_worklist")
        workflow.context_json = "{}"
        workflow.artifacts_json = "[]"
        workflow.stage = "preparing"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "正在重新生成核销日清"
        workflow.error_message = ""
        _message(db, workflow, "assistant", "旧清单作废，正在基于当前文件重新生成日清。", source)
        return
    if action == "cancel":
        if workflow.stage in BUSY_STAGES:
            context = _load(workflow.context_json, {})
            context["stop_after_action"] = True
            workflow.context_json = _json(context)
            _message(
                db,
                workflow,
                "assistant",
                "当前原子动作正在执行，不能从中间截断；完成后我会停止，不会继续下一阶段。",
                source,
            )
        else:
            workflow.stage = "cancelled"
            workflow.state = "cancelled"
            workflow.progress_message = "对话任务已取消"
            db.execute(
                update(WorkflowAction)
                .where(
                    WorkflowAction.workflow_id == workflow.id,
                    WorkflowAction.state == "queued",
                )
                .values(state="cancelled", finished_at=datetime.now(UTC))
            )
            _message(db, workflow, "assistant", "本次核销已取消，没有继续执行写入。", source)
        return
    _message(db, workflow, "assistant", _status_reply(workflow), source)


def send_workflow_message(
    db: Session,
    workflow: WorkflowSession,
    content: str,
    user: UserContext,
) -> WorkflowSession:
    _message(db, workflow, "user", content)
    db.flush()
    recent = list(
        db.scalars(
            select(WorkflowMessage)
            .where(WorkflowMessage.workflow_id == workflow.id)
            .order_by(WorkflowMessage.id.desc())
            .limit(20)
        ).all()
    )
    history = [
        {"role": item.role, "content": item.content}
        for item in reversed(recent)
        if item.role in {"user", "assistant"}
    ]
    llm = resolve_runtime_config(
        db,
        user,
        workflow.model_connection_id,
        workflow.model_name,
    )
    decision = decide_workflow_turn(
        llm,
        workflow.stage,
        content,
        workflow.reconciliation_date,
        history,
    )
    if decision.action == "confirm_date" and not _is_explicit_confirmation(
        content,
        apply=False,
    ):
        decision = WorkflowDecision("show_status", {}, "backend_guard")
    if decision.action == "confirm_apply" and not _is_explicit_confirmation(
        content,
        apply=True,
    ):
        decision = WorkflowDecision("show_status", {}, "backend_guard")
    _apply_decision(db, workflow, decision)
    db.commit()
    db.refresh(workflow)
    return workflow


def claim_next_workflow_action(db: Session, pools: tuple[str, ...]) -> WorkflowAction | None:
    if "workflow" not in pools:
        return None
    action_id = db.scalar(
        select(WorkflowAction.id)
        .where(WorkflowAction.state == "queued")
        .order_by(WorkflowAction.queued_at.asc())
        .limit(1)
    )
    if not action_id:
        return None
    now = datetime.now(UTC)
    claimed = db.execute(
        update(WorkflowAction)
        .where(WorkflowAction.id == action_id, WorkflowAction.state == "queued")
        .values(state="running", started_at=now)
    )
    db.commit()
    return db.get(WorkflowAction, action_id) if claimed.rowcount == 1 else None


def _copy_inputs(db: Session, action: WorkflowAction, business: Path) -> None:
    payload = _load(action.input_json, {})
    for role, folder_name in FILE_ROLES.items():
        target_dir = business / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in payload.get("files", {}).get(role, []):
            record = db.get(FileRecord, item["file_id"])
            if not record:
                raise RuntimeError(f"输入记录不存在：{item['file_id']}")
            source = Path(record.stored_path).resolve()
            if not source.is_file() or sha256_file(source) != record.sha256:
                raise RuntimeError(f"输入文件完整性校验失败：{record.id}")
            target = target_dir / safe_filename(record.original_name)
            if target.exists():
                target = target_dir / f"{target.stem}_{record.id[:8]}{target.suffix}"
            shutil.copy2(source, target)
    for folder_name in ("03_台账", "04_产出"):
        (business / folder_name).mkdir(parents=True, exist_ok=True)


def _run_script(
    script_dir: Path,
    script_name: str,
    arguments: list[str],
    timeout: int = 900,
    stdin_data: str | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> str:
    command = [sys.executable, str(script_dir / script_name), *arguments]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        command,
        cwd=script_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin_data,
        timeout=timeout,
        env=env,
        check=False,
    )
    if completed.returncode:
        details = (completed.stderr or completed.stdout).strip()
        for value in sensitive_values:
            if value:
                details = details.replace(value, "[已隐藏]")
        suffix = f"：{details[-1200:]}" if details else ""
        raise RuntimeError(
            f"{script_name} 执行失败（退出码 {completed.returncode}）{suffix}"
        )
    return completed.stdout


def _register_artifact(
    db: Session,
    workflow: WorkflowSession,
    source: Path,
    action_id: str,
) -> dict[str, Any]:
    root = (settings.workflow_dir / workflow.id).resolve()
    source = source.resolve()
    if not source.is_file() or not source.is_relative_to(root):
        raise RuntimeError("工作流产物必须位于当前会话目录。")
    delivery = root / "outputs" / action_id
    delivery.mkdir(parents=True, exist_ok=True)
    target = delivery / safe_filename(source.name)
    if target.exists() and source != target:
        digest = sha256_file(source)[:8]
        target = delivery / f"{target.stem}_{digest}{target.suffix}"
    if source != target:
        shutil.copy2(source, target)
    record = FileRecord(
        id=str(uuid.uuid4()),
        owner_id=workflow.owner_id,
        department_id=workflow.department_id,
        kind="output",
        original_name=target.name,
        stored_path=str(target.resolve()),
        content_type="application/octet-stream",
        size_bytes=target.stat().st_size,
        sha256=sha256_file(target),
    )
    db.add(record)
    db.flush()
    return {
        "name": record.original_name,
        "file_id": record.id,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "download_url": f"/api/files/{record.id}/download",
        "action_id": action_id,
    }


def _worklist_summary(stdout: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    line = next((item for item in stdout.splitlines() if "《核销日清》已生成：" in item), "")
    for label in ("今天要填", "已填过·跳过", "冲突·需你定", "挂账待办", "异常"):
        match = re.search(rf"{re.escape(label)}\s+(\d+)", line)
        if match:
            summary[label] = int(match.group(1))
    flow = next((item for item in stdout.splitlines() if item.startswith("流转：")), "")
    for label in ("确认后自动写", "须手填", "跳过"):
        match = re.search(rf"{label}\s+(\d+)", flow)
        if match:
            summary[f"流转{label}"] = int(match.group(1))
    return summary


def _prepare_worklist(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
) -> dict[str, Any]:
    root = (settings.workflow_dir / workflow.id).resolve()
    business = root / "actions" / action.id / "工作区"
    business.mkdir(parents=True, exist_ok=False)
    _copy_inputs(db, action, business)
    script_dir = root / "skill" / "vendor" / "scripts"
    if not (script_dir / "classify_hexiao.py").is_file():
        raise RuntimeError("应收核销脚本包不完整。")
    workspace = str(business.resolve())
    hexiao_date = workflow.reconciliation_date
    account, password = resolve_service_credential(
        db,
        workflow.owner_id,
        workflow.department_id,
        "zhiyun",
    )
    workflow.progress = 10
    workflow.progress_message = "正在登录智云并按核销日期自动取数"
    db.commit()
    try:
        _run_script(
            script_dir,
            "fetch_secure.py",
            [],
            timeout=600,
            stdin_data=_json(
                {
                    "account": account,
                    "password": password,
                    "reconciliation_date": hexiao_date,
                    "workspace": workspace,
                }
            ),
            sensitive_values=(account, password),
        )
    finally:
        password = ""
    steps = [
        ("inspect_inputs.py", ["--workspace", workspace]),
        ("verify_sources.py", ["snapshot", "--workspace", workspace]),
        (
            "classify_hexiao.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date],
        ),
        (
            "validate_plan.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date],
        ),
        (
            "build_flow_plan.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date],
        ),
    ]
    for index, (script, arguments) in enumerate(steps, start=1):
        workflow.progress = 20 + index * 11
        workflow.progress_message = f"正在执行日清准备步骤 {index}/{len(steps) + 1}"
        db.commit()
        _run_script(script_dir, script, arguments)
    stdout = _run_script(
        script_dir,
        "build_worklist.py",
        ["--workspace", workspace, "--hexiao-date", hexiao_date],
    )
    worklists = sorted(
        (business / "04_产出").glob("核销日清_*.xlsx"),
        key=lambda path: path.stat().st_mtime,
    )
    if not worklists:
        raise RuntimeError("build_worklist.py 未生成核销日清。")
    artifact = _register_artifact(db, workflow, worklists[-1], action.id)
    checked = sorted(
        (business / "04_产出").glob("写入计划_校验后*.json"),
        key=lambda path: path.stat().st_mtime,
    )
    ledgers = sorted((business / "02_我的表副本").glob("*盈亏*.xls*"))
    if not checked or not ledgers:
        raise RuntimeError("日清已生成，但没有找到校验后计划或盈亏副本。")
    summary = _worklist_summary(stdout)
    return {
        "workspace": str(business),
        "checked_plan": str(checked[-1]),
        "ledger": str(ledgers[0]),
        "summary": summary,
        "artifacts": [artifact],
    }


def _apply_confirmed(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
) -> dict[str, Any]:
    context = _load(action.input_json, {}).get("context", {})
    business = Path(context.get("workspace", "")).resolve()
    root = (settings.workflow_dir / workflow.id).resolve()
    if not business.is_dir() or not business.is_relative_to(root):
        raise RuntimeError("上一次日清工作区不存在，请重新生成日清。")
    script_dir = root / "skill" / "vendor" / "scripts"
    checked = Path(context.get("checked_plan", "")).resolve()
    ledger = Path(context.get("ledger", "")).resolve()
    if not checked.is_file() or not ledger.is_file():
        raise RuntimeError("校验后计划或盈亏副本不存在，请重新生成日清。")
    workspace = str(business)
    _run_script(
        script_dir,
        "apply_all.py",
        [
            "--checked",
            str(checked),
            "--ledger",
            str(ledger),
            "--workspace",
            workspace,
            "--confirmed",
            "--in-place",
            "--flow-in-place",
        ],
    )
    _run_script(script_dir, "verify_sources.py", ["verify", "--workspace", workspace])
    candidates = [
        path
        for folder in (business / "02_我的表副本", business / "04_产出")
        for path in folder.glob("*")
        if path.is_file()
        and path.suffix.lower() in {".xlsx", ".xlsm", ".json", ".txt"}
        and ("备份" not in path.name)
    ]
    artifacts = [_register_artifact(db, workflow, path, action.id) for path in candidates]
    return {"workspace": str(business), "artifacts": artifacts}


def execute_workflow_action(db: Session, action: WorkflowAction) -> None:
    workflow = db.get(WorkflowSession, action.workflow_id)
    if not workflow:
        action.state = "failed"
        action.error_message = "对话任务不存在。"
        action.finished_at = datetime.now(UTC)
        return
    try:
        if action.name == "prepare_worklist":
            result = _prepare_worklist(db, action, workflow)
            context = _load(workflow.context_json, {})
            context.update(result)
            workflow.context_json = _json(context)
            artifacts = _load(workflow.artifacts_json, [])
            artifacts.extend(result["artifacts"])
            workflow.artifacts_json = _json(artifacts)
            stop = bool(context.get("stop_after_action"))
            workflow.stage = "cancelled" if stop else "awaiting_apply_confirmation"
            workflow.state = "cancelled" if stop else "waiting_confirmation"
            workflow.progress = 100
            workflow.progress_message = (
                "日清生成后按要求停止" if stop else "核销日清已生成，等待人工确认"
            )
            summary = result.get("summary", {})
            if stop:
                reply = "《核销日清》已经生成，但按你的停止要求，本次不会进入写表阶段。"
            else:
                reply = (
                    f"✅ 核销日期 {_date_label(workflow.reconciliation_date)} 的核销判定完了，"
                    "财务工作簿原件一个字节没动；智云只做了查询取数。\n"
                    f"盈亏：今天要填 {summary.get('今天要填', 0)} 行；"
                    f"已填过·跳过 {summary.get('已填过·跳过', 0)} 行；"
                    f"冲突·需你定 {summary.get('冲突·需你定', 0)} 行；"
                    f"挂账待办 {summary.get('挂账待办', 0)} 行；"
                    f"异常 {summary.get('异常', 0)} 行。\n"
                    f"流转：确认后自动写 {summary.get('流转确认后自动写', 0)} 笔；"
                    f"须你手填 {summary.get('流转须手填', 0)} 笔。\n"
                    "请下载并打开《核销日清》检查；没问题回复“确认”或“可以写”。"
                )
            _message(db, workflow, "assistant", reply, {"kind": "worklist_ready"})
        elif action.name == "apply_confirmed":
            result = _apply_confirmed(db, action, workflow)
            context = _load(workflow.context_json, {})
            context.update(result)
            workflow.context_json = _json(context)
            artifacts = _load(workflow.artifacts_json, [])
            artifacts.extend(result["artifacts"])
            workflow.artifacts_json = _json(artifacts)
            workflow.stage = "completed"
            workflow.state = "succeeded"
            workflow.progress = 100
            workflow.progress_message = "盈亏和流转写入完成并通过回读校验"
            _message(
                db,
                workflow,
                "assistant",
                "统一写入完成：先盈亏明细、后流转安全子集，回读校验已通过。"
                "结果文件已放到右侧下载区。",
                {"kind": "workflow_completed"},
            )
        else:
            raise RuntimeError(f"不支持的工作流动作：{action.name}")
        action.result_json = _json(result)
        action.state = "succeeded"
        action.finished_at = datetime.now(UTC)
        workflow.error_message = ""
    except subprocess.TimeoutExpired:
        action.state = "failed"
        action.error_message = "脚本执行超时。"
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.error_message = action.error_message
        workflow.progress_message = "动作执行超时"
        _message(
            db,
            workflow,
            "assistant",
            "这一步执行超时，财务工作簿原件没有被修改。请检查材料后回复“重出日清”。",
            {"kind": "action_failed"},
        )
    except Exception as exc:
        action.state = "failed"
        action.error_message = str(exc)[:500]
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.error_message = action.error_message
        workflow.progress_message = "动作没有完成"
        _message(
            db,
            workflow,
            "assistant",
            f"这一步没有完成：{action.error_message}。财务工作簿原件没有被修改。"
            "请检查材料后回复“重出日清”。",
            {"kind": "action_failed"},
        )


def run_workflow_action_once(db: Session, pools: tuple[str, ...]) -> bool:
    action = claim_next_workflow_action(db, pools)
    if not action:
        return False
    execute_workflow_action(db, action)
    db.commit()
    return True
