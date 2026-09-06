"""Queue and run a separate, read-only investigation without changing AR outcome."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException

from .ar_execution_contract import CONTRACT_VERSION, INVESTIGATION_ACTION, ExecutionLeaseLost, next_phase
from .models import WorkflowMaterialSet

MAX_INVESTIGATIONS = 2


def investigation_status(workflow, *, ignore_action_id: str = "") -> dict:
    result = {"allowed": False, "reason": "当前没有可调查的失败写入阶段。", "failed_action_id": "",
              "checkpoint_fingerprint": "", "action_id": "", "state": "not_started", "summary": {}, "cancel_allowed": False}
    context = json.loads(workflow.context_json or "{}")
    state, failure = context.get("ar_execution") or {}, context.get("ar_failure") or {}
    if state.get("schema_version") != CONTRACT_VERSION or workflow.state != "failed":
        return result
    try:
        phase = next_phase(state.get("completed") or [])
    except ValueError:
        return {**result, "reason": "原执行阶段记录不完整，不能确定调查对象。"}
    failed = next((item for item in workflow.actions if item.id == failure.get("action_id")), None)
    if (phase is None or phase.name not in {"write_ledger", "write_receipt_flow"}
            or failed is None or failed.state != "failed" or not failed.finished_at
            or failed.name != f"ar_{phase.name}" or failure.get("phase") != phase.name):
        return result
    basis = {"execution": state, "failure": failure, "workflow_id": workflow.id,
             "owner_id": workflow.owner_id, "department_id": workflow.department_id,
             "reconciliation_date": workflow.reconciliation_date, "skill_hash": workflow.skill_hash,
             "material_set_id": workflow.material_set_id,
             "inputs": {name: context.get(name) for name in ("workspace", "checked_plan", "plan_fingerprint", "ledger_years", "flow_file")},
             "failed_action": {"id": failed.id, "attempt": failed.attempt_count, "finished_at": str(failed.finished_at)}}
    result.update(failed_action_id=failed.id, checkpoint_fingerprint=hashlib.sha256(
        json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest())
    investigations = [item for item in workflow.actions if item.name == INVESTIGATION_ACTION
                      and json.loads(item.input_json or "{}").get("failed_action_id") == failed.id]
    if investigations:
        latest = max(investigations, key=lambda item: item.queued_at)
        recorded = json.loads(latest.result_json or "{}")
        result.update(action_id=latest.id, state=latest.state, summary=recorded.get("public_result") or {},
                      action_error=latest.error_message, cancel_allowed=latest.state in {"queued", "running"})
        if json.loads(latest.input_json or "{}").get("cancel_requested") and latest.state in {"queued", "running"}:
            return {**result, "cancel_allowed": False, "reason": "已申请停止调查，等待当前调查脚本退出；原核销失败记录保留。"}
    if any(item.state in {"running", "queued"} and item.id != ignore_action_id for item in workflow.actions):
        return {**result, "reason": "仍有动作排队或执行中，不能重复派发调查。"}
    if sum(item.id != ignore_action_id for item in investigations) >= MAX_INVESTIGATIONS:
        return {**result, "reason": "本次失败写入已调查两次；保留全部结果，后续需通过关联恢复任务处理。"}
    return {**result, "allowed": True,
            "reason": "可在隔离副本中调查实际写入结果；原任务保持失败，不重新核销或发布。"}


def _original_binding(db, workflow) -> None:
    from . import workflow_service as service
    from .ar_execution_runner import execution_version

    service.workflow_owner_context(db, workflow)
    service.assert_workflow_execution_enabled(workflow)
    context = json.loads(workflow.context_json or "{}")
    state = context.get("ar_execution") or {}
    material = db.get(WorkflowMaterialSet, state.get("material_set_id"))
    if (execution_version(workflow) != CONTRACT_VERSION or material is None
            or material.owner_id != workflow.owner_id or material.department_id != workflow.department_id
            or material.skill_id != workflow.skill_id or material.version != state.get("material_version")
            or state.get("reconciliation_date") != workflow.reconciliation_date
            or state.get("skill_hash") != workflow.skill_hash):
        raise HTTPException(status_code=409, detail="原任务的固定 Skill、日期或材料身份无法核实，未启动调查。")
    # This may inspect an old immutable material version, but never publishes it.


def queue_investigation(db, workflow, request, actor) -> None:
    from . import workflow_service as service
    from .scheduler import acquire_claim_lock

    db.commit()
    acquire_claim_lock(db)
    db.refresh(workflow)
    db.expire(workflow, ["actions"])
    _original_binding(db, workflow)
    service._assert_single_flight_available(db, workflow.skill_id, exclude_workflow_id=workflow.id,
                                           exclude_batch_id=workflow.batch_id or "")
    status = investigation_status(workflow)
    if (not status["allowed"] or request.failed_action_id != status["failed_action_id"]
            or request.checkpoint_fingerprint != status["checkpoint_fingerprint"]):
        raise HTTPException(status_code=409, detail=status["reason"] if not status["allowed"] else "原失败执行记录已变化，请刷新后调查。")
    service._new_action(db, workflow, INVESTIGATION_ACTION, {
        "failed_action_id": status["failed_action_id"], "checkpoint_fingerprint": status["checkpoint_fingerprint"],
        "requested_by": actor.user_id,
    })
    service.record_audit(db, actor=actor, action="workflow.ar_execution.investigate", resource_type="workflow",
                         resource_id=workflow.id, details={"failed_action_id": status["failed_action_id"]})
    db.commit()


def lock_investigation(db, action, workflow) -> None:
    from .scheduler import acquire_claim_lock

    expected_worker = getattr(action, "_ar_claim_worker_id", action.worker_id)
    db.commit()
    acquire_claim_lock(db)
    db.refresh(action)
    db.refresh(workflow)
    db.expire(workflow, ["actions"])
    deadline = action.lease_expires_at
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if (action.name != INVESTIGATION_ACTION or action.state != "running" or not expected_worker
            or action.worker_id != expected_worker or deadline is None or deadline <= datetime.now(UTC)):
        raise ExecutionLeaseLost("调查动作租约已失效，旧 Worker 不能登记调查结果。")


def _validate_request(db, action, workflow) -> tuple[dict, dict]:
    from . import workflow_service as service

    _original_binding(db, workflow)
    service._assert_single_flight_available(db, workflow.skill_id, exclude_workflow_id=workflow.id,
                                           exclude_batch_id=workflow.batch_id or "")
    request = json.loads(action.input_json or "{}")
    if request.get("cancel_requested"):
        raise HTTPException(status_code=409, detail="已按请求停止独立调查，原核销失败记录保留。")
    status = investigation_status(workflow, ignore_action_id=action.id)
    if (not status["allowed"] or request.get("failed_action_id") != status["failed_action_id"]
            or request.get("checkpoint_fingerprint") != status["checkpoint_fingerprint"]):
        raise HTTPException(status_code=409, detail="调查对象或原执行检查点已变化，停止本次调查登记。")
    return request, json.loads(workflow.context_json or "{}")


def cancel_investigation(db, workflow, actor) -> bool:
    from . import workflow_service as service

    active = [item for item in workflow.actions if item.name == INVESTIGATION_ACTION and item.state in {"queued", "running"}]
    if not active:
        return False
    for action in active:
        request = json.loads(action.input_json or "{}")
        request["cancel_requested"] = True
        action.input_json = service._json(request)
        if action.state == "queued":
            action.state, action.finished_at = "cancelled", datetime.now(UTC)
            action.error_message = "调查在启动前取消，原核销失败记录保留。"
    service.record_audit(db, actor=actor, action="workflow.ar_execution.investigation.cancel",
                         resource_type="workflow", resource_id=workflow.id,
                         details={"action_ids": [item.id for item in active]})
    return True


def _public_row_problems(problems: list) -> list[dict]:
    """Publish location and check type, never raw cell values or exception text."""
    fields = {"计提", "回款明细", "是否结账", "收款时间", "收款方式", "差异", "差异公式", "SOD", "应收金额"}
    items = []
    for problem in problems[:50]:
        raw = str(problem)
        location = re.match(r"第 ([1-9][0-9]{0,6}) 行(?: ([^：]+)：)?", raw)
        field = location.group(2) if location else ""
        item: dict[str, object] = {"message": "单元格或拆行组回读与固定计划不一致。"}
        if location:
            item["row"] = int(location.group(1))
            if field in fields:
                item["field"] = field
                item["message"] = "字段实际结果与预期不一致。"
        elif "合计不守恒" in raw:
            item["message"] = "拆行组的应收、回款或计提合计与计划不一致。"
        elif "保留应收拆行组" in raw:
            item["message"] = "保留应收拆行组的身份、空值、金额或结账状态不一致。"
        case = re.match(r"(AR[0-9]{1,24}\|SO[0-9]{1,24}\|SOD[0-9]{1,24})(?:\s|$)", raw)
        if case:
            item["case_id"] = case.group(1)
        items.append(item)
    return items


def _public_result(payload: dict) -> dict:
    # Workbook names, row values, paths and raw patcher errors stay private.
    labels = {"matches_expected": "实际文件与固定计划推导的预期结果一致。",
              "unchanged_no_write": "本年度没有待写记录，文件保持原样。",
              "unexpected_change": "固定计划不要求改动，实际文件却已变化。",
              "differs_from_expected": "实际文件或单元格与预期不一致，写入结果未确认。",
              "not_started_unchanged": "流程尚未进入流转阶段，文件保持原样。",
              "baseline_retained": "流转保留写前副本，未体现完整计划结果。",
              "expected_plan_unresolved": "固定流转计划无法构造完整预期结果。",
              "invalid_package": "工作簿损坏、无法读取或超过解析上限。",
              "unconfirmed": "预期构造或实际回读未完成。"}
    items = []
    for year, entry in (payload.get("ledger_results") or {}).items():
        if not str(year).isdigit() or len(str(year)) != 4 or not isinstance(entry, dict):
            raise ValueError("调查年度结果格式无效")
        items.append({"label": f"{year} 年盈亏", "state": entry.get("state"),
                      "message": labels.get(entry.get("state"), "本年度结果尚未确认。"),
                      "row_problem_count": len(entry.get("row_problems") or []),
                      "row_problems": _public_row_problems(entry.get("row_problems") or [])})
    flow = payload.get("flow_result") or {}
    items.append({"label": "到账流转", "state": flow.get("state"),
                  "message": labels.get(flow.get("state"), "流转结果尚未确认。")})
    for index, entry in enumerate((payload.get("other_workbooks") or {}).values(), start=1):
        if not isinstance(entry, dict):
            raise ValueError("非目标工作簿调查结果格式无效")
        state = entry.get("state") or ("unchanged_no_write" if entry.get("verified") is True else "unexpected_change")
        items.append({"label": f"其他工作簿 {index}", "state": state,
                      "message": ("非目标工作簿与写前文件一致。" if entry.get("verified") is True
                                  else labels.get(state, "非目标工作簿结果未确认。"))})
    return {"inputs_unchanged": payload.get("inputs_unchanged") is True,
            "files_match_expected": payload.get("business_files_match_expected") is True,
            "message": ("本次调查副本与预期一致；原执行停止与发布状态仍须核查，不会自动重写。"
                        if payload.get("inputs_unchanged") is True and payload.get("business_files_match_expected") is True
                        else "存在文件差异或未完成的核查，具体原因逐项列明；不能据此恢复。"
                        if payload.get("inputs_unchanged") is True else "调查期间原输入变化，比较结果不能作为当前任务恢复依据。"),
            "items": items}


def execute_investigation(db, action, workflow) -> None:
    from . import workflow_service as service
    from .ar_execution_runner import ArExecution
    from .ar_process_evidence import SCHEMA_VERSION, run_recorded_script
    from .ar_process_inspection import inspect_process_evidence
    from .ar_investigation_readback import ASSESSMENT_VERSION, assess_write_result, read_investigation
    from .ar_write_inspection import WriteInspectionError

    action._ar_process_exit_confirmed = True
    action._ar_process_records = []
    try:
        lock_investigation(db, action, workflow)
        request, context = _validate_request(db, action, workflow)
        db.commit()
        # Large file checks/copies are outside the scheduler's claim transaction.
        execution = ArExecution(db, action, workflow)
        fixed_ledgers = execution.ledgers
        stage, checked = execution.staging()
        manifest_path = stage / "execution-manifest.json"
        manifest_sha = service.sha256_file(manifest_path)
        flow = service._staged_workspace_path(execution.workspace, stage, Path(context["flow_file"]))
        attempt = action.id.replace("-", "")
        arguments = ["--baseline", str(execution.workspace), "--workspace", str(stage),
                     "--checked", str(checked), "--flow-file", str(flow), "--manifest-sha256", manifest_sha,
                     "--workflow-id", workflow.id, "--phase", context["ar_failure"]["phase"], "--attempt", attempt]
        arguments += service._annual_ledger_arguments(fixed_ledgers)
        lock_investigation(db, action, workflow)
        _validate_request(db, action, workflow)
        db.commit()
        stdout = run_recorded_script(execution.scripts, "investigate_failed_write.py", arguments,
                                     action=action, workflow=workflow)
        response = json.loads(stdout.strip())
        report = stage / "execution-investigations" / attempt / "result.json"
        if (not report.is_file() or report.is_symlink() or not report.resolve().is_relative_to(stage)
                or report.stat().st_size > 16 * 1024 * 1024):
            raise ValueError("独立调查报告缺失或超出范围")
        with report.open("rb") as handle:
            raw = handle.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("调查报告超过大小限制")
        fingerprint = hashlib.sha256(raw).hexdigest()
        if response.get("schema_version") != "ar-write-investigation-v1" or response.get("report_sha256") != fingerprint:
            raise ValueError("独立调查报告与脚本完成凭据不一致")
        payload = json.loads(raw)
        if (payload.get("schema_version") != "ar-write-investigation-v1" or payload.get("workflow_id") != workflow.id
                or payload.get("attempt") != attempt or payload.get("manifest_sha256") != manifest_sha
                or payload.get("plan_sha256") != execution.execution["steps"]["stage_reconciliation"]["manifest"]["staged_plan_fingerprint"]
                or payload.get("material_set_id") != execution.execution.get("material_set_id")
                or payload.get("reconciliation_date") != workflow.reconciliation_date
                or payload.get("failed_phase") != context["ar_failure"]["phase"]
                or payload.get("authorizes_resume") is not False or payload.get("publication_verified") is not False):
            raise ValueError("独立调查报告与原执行输入绑定不一致")
        public = _public_result(payload)
        failed = next(item for item in workflow.actions if item.id == request["failed_action_id"])
        process = inspect_process_evidence(workflow, failed, context["ar_failure"])
        public["process_message"] = process["message"]
        # Keep the completed historical comparison even if its inputs became
        # stale; only the fresh readback can be used for recovery assessment.
        proof = None
        try:
            proof = read_investigation(workflow, action, {"path": str(report), "sha256": fingerprint})
            assessment = assess_write_result(workflow, proof.payload, proof.fingerprint)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            assessment = {"schema_version": ASSESSMENT_VERSION, "inputs_current": False,
                          "authorizes_resume": False, "code": "investigation_not_reusable",
                          "message": str(exc) if isinstance(exc, WriteInspectionError)
                          else "当前文件与调查报告未通过完整核对；保留历史调查，不能据此放行恢复。"}
        lock_investigation(db, action, workflow)
        _validate_request(db, action, workflow)
        if proof is not None:
            try:
                proof.check_unchanged()
            except (OSError, ValueError):
                assessment = {"schema_version": ASSESSMENT_VERSION, "inputs_current": False,
                              "authorizes_resume": False, "code": "inputs_changed_before_registration",
                              "message": "登记调查结果前输入文件发生变化，历史比较保留，不能用于当前恢复。"}
        assessment["checked_at"] = datetime.now(UTC).isoformat()
        assessment["message"] += " 以上为本次调查登记时的结果，发起恢复时必须重新读取。"
        public["recovery_assessment"] = assessment
        public["message"] += " " + assessment["message"]
        action.result_json = service._json({"report": {"path": str(report), "sha256": fingerprint},
                                           "failed_action_id": failed.id, "public_result": public,
                                           "recovery_assessment": assessment,
                                           "process_records": action._ar_process_records,
                                           "process_evidence_version": SCHEMA_VERSION})
        action.state, action.finished_at, action.error_message = "succeeded", datetime.now(UTC), ""
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            lock_investigation(db, action, workflow)
        except ExecutionLeaseLost:
            db.rollback()
            db.info["ar_execution_lease_lost"] = True
            return
        cancelled = json.loads(action.input_json or "{}").get("cancel_requested") is True
        action.state, action.finished_at = "cancelled" if cancelled else "failed", datetime.now(UTC)
        action.error_message = (str(exc.detail) if isinstance(exc, HTTPException)
                                else "独立调查未完成，已保留调查材料；原失败核销任务保持原状态。")
        action.result_json = service._json({"failed_action_id": json.loads(action.input_json or "{}").get("failed_action_id"),
                                           "error_type": type(exc).__name__,
                                           "process_exit_confirmed": action._ar_process_exit_confirmed,
                                           "process_records": action._ar_process_records,
                                           "process_evidence_version": SCHEMA_VERSION})
        db.commit()
