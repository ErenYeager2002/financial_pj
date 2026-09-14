"""Chat bridge to the existing AR executor; no financial write implementation."""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import UserContext
from .models import AssistantMessage
from .schemas import WorkflowBatchStart

STATE_KEY = "_assistant_workflow_v1"
AR_SKILLS = {"ar-hexiao-daily", "ar-hexiao-daily-lab"}

class AssistantWorkflowPrepare(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    message: str = Field(min_length=1, max_length=4000)
    skill_id: Literal["ar-hexiao-daily", "ar-hexiao-daily-lab"]
    reconciliation_dates: list[str] = Field(min_length=1, max_length=31)
    rerun_successful_dates: bool = False
    authorization_quote: str = Field(default="", max_length=1000)

class AssistantWorkflowStart(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    message: str = Field(min_length=1, max_length=4000)
    plan_id: str = Field(min_length=1, max_length=64)

def _message(db, user, session_id, content):
    row = db.scalar(select(AssistantMessage).where(
        AssistantMessage.owner_id == user.user_id,
        AssistantMessage.department_id == user.department_id,
        AssistantMessage.session_id == session_id,
        AssistantMessage.role == "user",
    ).order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc()).limit(1).with_for_update())
    if row is None or row.content.strip() != content.strip():
        raise HTTPException(409, "会话已更新，请依据最新用户消息重新检查。")
    return row

def _metadata(row):
    value = json.loads(row.data_json or "{}")
    return value if isinstance(value, dict) else {}

def _fingerprint(files, material):
    payload = {"version": material.get("material_set_id"), "files": {
        role: sorted((item["file_id"], item["sha256"]) for item in entries)
        for role, entries in files.items()}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def inspect_materials(db: Session, user: UserContext, skill_id: str):
    from .workflow_service import reusable_workflow_files, has_service_credential
    if skill_id not in AR_SKILLS:
        raise HTTPException(422, "此入口仅支持应收核销标准版和极速版。")
    files, missing, material = reusable_workflow_files(db, skill_id, user)
    credential_ready = has_service_credential(db, user.user_id, user.department_id, "zhiyun")
    return {"skill_id": skill_id, "ready": not missing and credential_ready,
        "missing_roles": missing, "zhiyun_credential_ready": credential_ready,
        "material_version": material.get("material_version"),
        "material_source": "current_version" if material.get("material_set_id") else "uploaded_inputs",
        "files": [{"role": role, "name": item["name"], "year": item.get("year")}
                  for role, entries in files.items() for item in entries]}, _fingerprint(files, material)


def _execution_intent(message: str) -> bool:
    # Inspect the whole user's message, never an action word cut out of a denial.
    text = re.sub(r'```[\s\S]*?```|「[^」]*」|“[^”]*”|"[^"]*"', '', message).strip()
    if re.search(r"不要|暂不|先不|别执行|别跑|别做|不需要|取消|停止|只(?:是|想)?(?:问|查|看|了解)|假如|假设|举例|比如", text):
        return False
    if re.search(r"什么|哪些|能否|能不能|能.*吗|是否|条件|流程|方案", text) and not re.search(r"帮我(?:执行|跑|做)|请(?:执行|跑)|直接(?:执行|跑)", text):
        return False
    if re.search(r"为什么|如何|怎么", text) and not re.search(r"帮我(?:执行|跑|做)|立即(?:执行|跑)|直接(?:执行|跑)", text):
        return False
    return bool(re.search(r"执行|启动|开始|继续|(?:帮我|给我)?跑|帮我做|做.*(?:核销|任务)|再做|重新做|^(?:可以|好的|好|行|确认|同意)[，。！!\s]*(?:就这样)?$", text))


def _rerun_intent(db, user, body):
    if re.search(r"重跑|重新(?:核销|执行|跑|做)|再(?:跑|执行|做).*次", body.message):
        return True
    # Continue only a matching server-owned plan; an old command about another
    # date or Skill cannot authorize rerunning this request.
    rows = db.scalars(select(AssistantMessage).where(
        AssistantMessage.owner_id == user.user_id, AssistantMessage.department_id == user.department_id,
        AssistantMessage.session_id == body.session_id, AssistantMessage.role == "user",
    ).order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc()).limit(20)).all()
    for row in rows:
        if re.search(r"不要|取消|停止|不重跑", row.content):
            return False
        plan = _metadata(row).get(STATE_KEY, {})
        if plan:
            request = plan.get("request", {})
            return (plan.get("state") in {"prepared", "awaiting_materials"} and bool(request.get("rerun_successful_dates"))
                    and request.get("skill_id") == body.skill_id
                    and request.get("reconciliation_dates") == sorted(set(body.reconciliation_dates)))
    return False


def check_execution_state(db, user, skill_id, dates):
    from .workflow_service import _assert_single_flight_available, _workflow_has_started_write
    from .models import WorkflowSession, WorkflowMaterialSet
    from .workflow_material_service import current_material_set
    _assert_single_flight_available(db, skill_id)
    current = current_material_set(db, user.user_id, user.department_id, skill_id)
    lineage = set()
    while current is not None and current.id not in lineage:
        lineage.add(current.id)
        current = db.get(WorkflowMaterialSet, current.parent_set_id) if current.parent_set_id else None
    rows = db.scalars(select(WorkflowSession).where(
        WorkflowSession.owner_id == user.user_id, WorkflowSession.department_id == user.department_id,
        WorkflowSession.skill_id == skill_id, WorkflowSession.reconciliation_date.in_(dates),
        WorkflowSession.material_set_id.in_(lineage) if lineage else WorkflowSession.material_set_id.is_(None),
    ).order_by(WorkflowSession.created_at.desc())).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.reconciliation_date, row)
    successful = []
    for row in latest.values():
        if row.state == "succeeded":
            successful.append(row.reconciliation_date)
        elif row.state in {"failed", "cancelled"}:
            context = json.loads(row.context_json or "{}")
            # Staged execution has its own recovery and investigation actions.
            staged = context.get("ar_execution") or context.get("ar_failure")
            if staged or _workflow_has_started_write(row):
                raise HTTPException(409, f"{row.display_id or row.id} 存在失败或中断的核销执行，请先在原任务查看恢复/调查结果，不能自动从头重跑。")
    return sorted(successful)

def prepare(db: Session, user: UserContext, body: AssistantWorkflowPrepare):
    from .workflow_service import _parse_date
    row = _message(db, user, body.session_id, body.message)
    metadata = _metadata(row)
    previous = metadata.get(STATE_KEY, {})
    if previous.get("state") in {"starting", "started", "failed"}:
        raise HTTPException(409, "这条指令已经提交过启动。请查询任务状态，不要自动重试。")
    dates = sorted(set(body.reconciliation_dates))
    parsed = [_parse_date(value) for value in dates]
    if any(value is None for value in parsed) or (parsed[-1] - parsed[0]).days > 30:
        raise HTTPException(422, "核销日期无效、晚于今天或跨度超过31天。")
    quote = body.authorization_quote.strip()
    if quote and quote not in body.message:
        raise HTTPException(422, "执行依据必须引用当前用户消息的原文。")
    if quote and not _execution_intent(body.message):
        raise HTTPException(422, "当前消息没有明确执行要求，保持只读查询。")
    if body.rerun_successful_dates and (not quote or not _rerun_intent(db, user, body)):
        raise HTTPException(422, "重新核销已成功日期需要当前用户明确要求重跑的原文。")
    summary, fingerprint = inspect_materials(db, user, body.skill_id)
    successful_dates = check_execution_state(db, user, body.skill_id, dates) if summary["ready"] else []
    plan = {"id": str(uuid.uuid4()), "state": "prepared", "created": datetime.now(timezone.utc).timestamp(),
        "fingerprint": fingerprint, "request": {"skill_id": body.skill_id,
        "reconciliation_dates": dates, "rerun_successful_dates": body.rerun_successful_dates,
        "rerun_reason": quote if body.rerun_successful_dates else ""}, "authorization_quote": body.message if quote else ""}
    if not summary["ready"]:
        plan["state"] = "awaiting_materials"
    metadata[STATE_KEY] = plan
    row.data_json = json.dumps(metadata, ensure_ascii=False)
    db.commit()
    return {**summary, "plan_id": plan["id"] if summary["ready"] else None, "reconciliation_dates": dates,
            "rerun_successful_dates": body.rerun_successful_dates, "successful_dates": successful_dates, "data_source": "live"}

def start(db: Session, user: UserContext, body: AssistantWorkflowStart):
    from .workflow_service import start_workflow_batch
    row = _message(db, user, body.session_id, body.message)
    metadata = _metadata(row)
    plan = metadata.get(STATE_KEY, {})
    if plan.get("id") != body.plan_id:
        raise HTTPException(409, "启动计划不存在，请先检查本次材料和日期。")
    if plan.get("state") == "started":
        return plan["result"]
    if plan.get("state") != "prepared":
        raise HTTPException(409, "启动已经尝试过，结果不确定时请查询任务，不能自动重复提交。")
    if datetime.now(timezone.utc).timestamp() - plan["created"] > 600:
        raise HTTPException(409, "启动计划已过期，请重新检查材料。")
    if not plan.get("authorization_quote"):
        raise HTTPException(422, "只有用户明确要求执行时才能启动，请引用当前执行指令检查计划。")
    # Commit the attempt before invoking the existing service which commits itself.
    # A lost response or process crash must never trigger a second financial run.
    plan["state"] = "starting"
    row.data_json = json.dumps(metadata, ensure_ascii=False)
    row_id = row.id
    db.commit()
    def before_start():
        summary, fingerprint = inspect_materials(db, user, plan["request"]["skill_id"])
        if not summary["ready"] or fingerprint != plan["fingerprint"]:
            raise HTTPException(409, "材料或凭据已变化，本次没有启动；请核实后发出新的执行指令。")
        check_execution_state(db, user, plan["request"]["skill_id"], plan["request"]["reconciliation_dates"])

    def on_created(batch):
        # Persist the link in the same transaction as the batch, so even a lost
        # HTTP response can be recovered without submitting another run.
        result = {"id": batch.id, "display_id": batch.display_id, "state": batch.state,
            "reconciliation_dates": json.loads(batch.reconciliation_dates_json),
            "url": f"/dashboard/workflows/batches/{batch.id}"}
        row = db.get(AssistantMessage, row_id)
        data = _metadata(row)
        data[STATE_KEY].update(state="started", result=result)
        row.data_json = json.dumps(data, ensure_ascii=False)

    try:
        start_workflow_batch(db, WorkflowBatchStart(**plan["request"]), user,
                             before_start=before_start, on_created=on_created)
    except Exception:
        db.rollback()
        row = db.get(AssistantMessage, row_id)
        data = _metadata(row)
        if data[STATE_KEY].get("state") == "started":
            return data[STATE_KEY]["result"]
        data[STATE_KEY]["state"] = "failed"
        row.data_json = json.dumps(data, ensure_ascii=False)
        db.commit()
        raise
    result = _metadata(db.get(AssistantMessage, row_id))[STATE_KEY]["result"]
    return result


def task_status(db: Session, user: UserContext, task_id: str):
    from sqlalchemy import or_
    from .models import WorkflowBatch, WorkflowSession
    for model, is_batch in ((WorkflowBatch, True), (WorkflowSession, False)):
        row = db.scalar(select(model).where(
            model.owner_id == user.user_id, model.department_id == user.department_id,
            or_(model.id == task_id, model.display_id == task_id)))
        if row is not None:
            return {"id": row.id, "display_id": row.display_id, "kind": "任务",
                    "skill_id": row.skill_id, "skill_name": row.skill_name,
                    "state": row.state, "progress": row.progress,
                    "progress_message": row.progress_message,
                    "url": f"/dashboard/workflows/{'batches/' if is_batch else ''}{row.id}"}
    raise HTTPException(404, "当前账号没有找到这个核销任务或批次。")


def request_status(db, user, session_id):
    rows = db.scalars(select(AssistantMessage).where(
        AssistantMessage.owner_id == user.user_id, AssistantMessage.department_id == user.department_id,
        AssistantMessage.session_id == session_id, AssistantMessage.role == "user",
    ).order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc()).limit(200)).all()
    plan = next((_metadata(row)[STATE_KEY] for row in rows if STATE_KEY in _metadata(row)), {})
    return {"state": plan.get("state", "not_prepared"), "task": plan.get("result"),
            "created": plan.get("created"), "request": plan.get("request"),
            "message": "提交结果不确定，请查任务列表，不要再次启动。" if plan.get("state") == "starting" else ""}
