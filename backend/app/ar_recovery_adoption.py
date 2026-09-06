"""Use independently confirmed old ledger results in a linked recovery task.

The source stays failed. New classification, evidence review and validation run
normally; only the ledger phase uses this path. Missing or stale recovery facts
never fall through to the ordinary financial writer.
"""
from __future__ import annotations

import json
from pathlib import Path

from .ar_business_investigation import investigation_status
from .ar_investigation_readback import assess_write_result, read_investigation
from .ar_write_inspection import WriteInspectionError, _workspace
from .models import AuditEvent, WorkflowSession

LINK_VERSION = "ar-linked-recovery-v1"
STOP_ACTION = "workflow.ar_recovery.stop_confirmed"


def _source(execution, link: dict):
    db, target = execution.db, execution.workflow
    if (not isinstance(link, dict) or link.get("schema_version") != LINK_VERSION
            or link.get("target_skill_hash") != target.skill_hash
            or link.get("source_workflow_id") != execution.context.get("recovery_source_workflow_id")
            or link.get("source_workflow_id") == target.id):
        raise WriteInspectionError("关联恢复身份或固定新版本缺失，不能转为普通盈亏写入。")
    source = db.get(WorkflowSession, link.get("source_workflow_id"))
    if source is None:
        raise WriteInspectionError("原失败任务不存在，不能采用旧盈亏结果。")
    db.refresh(source)
    db.expire(source, ["actions"])
    if (any(getattr(source, key) != getattr(target, key) for key in (
            "owner_id", "department_id", "skill_id", "reconciliation_date"))
            or source.skill_hash != link.get("source_skill_hash")
            or source.state != "failed" or source.material_set_id != target.material_set_id
            or any(item.state in {"queued", "running"} for item in source.actions)):
        raise WriteInspectionError("原任务与关联恢复的所有者、日期、版本或材料不一致。")
    execution.service.workflow_owner_context(db, source)
    status = investigation_status(source)
    if status["checkpoint_fingerprint"] != link.get("source_checkpoint_fingerprint"):
        raise WriteInspectionError("原失败检查点已变化，不能沿用关联恢复请求。")
    action = next((item for item in source.actions if item.id == link.get("investigation_action_id")), None)
    if action is None or action.state != "succeeded":
        raise WriteInspectionError("关联恢复引用的调查尚未完成或不存在。")
    reference = json.loads(action.result_json or "{}").get("report") or {}
    if reference.get("sha256") != link.get("investigation_sha256"):
        raise WriteInspectionError("关联恢复的调查报告登记已经变化。")
    # A separate explicit stop disposition is required for external writers.
    # A successful file comparison or the absence of a PID cannot create it.
    stop = db.get(AuditEvent, link.get("stop_audit_id")) if type(link.get("stop_audit_id")) is int else None
    expected = {"failed_action_id": status["failed_action_id"],
                "investigation_action_id": action.id, "investigation_sha256": reference["sha256"],
                "input_fingerprint": link.get("input_fingerprint"), "external_writers_stopped": True}
    if (stop is None or stop.action != STOP_ACTION or stop.resource_type != "workflow"
            or stop.resource_id != source.id or stop.department_id != source.department_id
            or stop.outcome != "success" or not stop.actor_id
            or any(json.loads(stop.details_json or "{}").get(key) != value for key, value in expected.items())):
        raise WriteInspectionError("原执行缺少与本次调查对应的外部写入停止确认记录。")
    return source, action, reference


def _read_source(execution, link: dict):
    source, action, reference = _source(execution, link)
    proof = read_investigation(source, action, reference)
    assessment = assess_write_result(source, proof.payload, proof.fingerprint)
    if (proof.fingerprint != link.get("input_fingerprint") or assessment.get("ledger_confirmed") is not True
            or assessment.get("process_facts_verified") is not True
            or assessment.get("code") not in {"ledger_confirmed_flow_pending", "writes_confirmed_review_pending", "ledger_confirmed_flow_baseline"}):
        raise WriteInspectionError("原盈亏、流转处置或脚本停止事实未通过当前核查，不能采用旧结果。")
    if assessment["code"] != "ledger_confirmed_flow_pending":
        raise WriteInspectionError("原任务已尝试流转，但本次恢复尚未固定流转采用或保留原副本的处理计划；已停止，未重复写入。")
    return source, proof


def _fence(execution, link: dict, proof) -> None:
    from .ar_execution_runner import lock_execution

    lock_execution(execution.db, execution.action, execution.workflow)
    execution.verify_input_binding()
    current = json.loads(execution.workflow.context_json or "{}")
    if current.get("ar_linked_recovery") != link:
        raise WriteInspectionError("当前恢复关联已变化，停止采用旧结果。")
    _source(execution, link)
    proof.check_unchanged()
    execution.db.commit()
    execution.db.info.pop("ar_execution_lock", None)


def adopt_ledger(execution) -> dict:
    link = execution.context.get("ar_linked_recovery")
    stage, checked = execution.staging()
    execution._require_staged_fingerprints(stage, "stage_reconciliation")
    source, proof = _read_source(execution, link)
    source_context = json.loads(source.context_json or "{}")
    source_workspace = _workspace(source, source_context)
    source_stage = proof.reader.path(source_context["ar_execution"]["steps"]["stage_reconciliation"]["staging_workspace"])
    source_files = {name: value for name, value in proof.payload["input_files"]["staging"].items()
                    if name in proof.payload["input_files"]["baseline"]}
    manifest = execution.execution["steps"]["stage_reconciliation"]["manifest"]
    if manifest["files"] != {name: value["sha256"] for name, value in proof.payload["input_files"]["baseline"].items()}:
        raise WriteInspectionError("当前材料与原写入基线不同，旧写入候选不能覆盖新材料。")
    ledger_files = {str(year): path.relative_to(execution.workspace).as_posix() for year, path in execution.ledgers.items()}
    flow_file = Path(execution.context["flow_file"]).relative_to(execution.workspace).as_posix()
    if ledger_files != proof.payload["ledger_files"] or flow_file != proof.payload["flow_file"]:
        raise WriteInspectionError("新旧任务的年度与流转对应关系不同，不能采用旧结果。")
    if source_workspace == execution.workspace or source_stage == stage:
        raise WriteInspectionError("关联恢复必须使用新任务自己的原材料和暂存空间。")
    attempt = execution.action.id.replace("-", "")
    request = {"schema_version": "ar-ledger-adoption-request-v1",
               "source_workflow_id": source.id, "target_workflow_id": execution.workflow.id,
               "source_skill_hash": source.skill_hash, "target_skill_hash": execution.workflow.skill_hash,
               "investigation_action_id": link["investigation_action_id"], "investigation_sha256": link["investigation_sha256"],
               "input_fingerprint": proof.fingerprint, "reconciliation_date": execution.date,
               "material_set_id": execution.execution["material_set_id"],
               "baseline_workspace": str(execution.workspace), "staging_workspace": str(stage),
               "source_workspace": str(source_stage), "source_files": source_files,
               "ledger_files": ledger_files, "flow_file": flow_file,
               "target_manifest_sha256": execution.service.sha256_file(stage / "execution-manifest.json")}
    _fence(execution, link, proof)
    request_path = stage / f"recovery-ledger-request-{attempt}.json"
    with request_path.open("x", encoding="utf-8") as handle:
        json.dump(request, handle, ensure_ascii=False, indent=2)
    request_sha = execution.service.sha256_file(request_path)
    shared = ["--workspace", str(stage), "--request", str(request_path), "--request-sha256", request_sha, "--attempt", attempt]
    stdout = execution.script("prepare_recovery_ledger.py", [*shared, "--baseline", str(execution.workspace), "--source", str(source_stage)])
    response = json.loads(stdout.strip())
    candidate = stage / "execution-recovery" / attempt / "result.json"
    if (response.get("prepared") is not True or response.get("authorizes_install") is not False
            or not candidate.is_file() or candidate.is_symlink() or not candidate.resolve().is_relative_to(stage)
            or execution.service.sha256_file(candidate) != response.get("result_sha256")):
        raise WriteInspectionError("新版本盈亏核查没有返回完整候选，未采用旧结果。")
    # Re-read live source evidence after the potentially long reconstruction.
    _, proof = _read_source(execution, link)
    _fence(execution, link, proof)
    stdout = execution.script("install_recovery_ledger.py", [*shared, "--candidate-sha256", response["result_sha256"]])
    markers = [line.removeprefix("AR_WRITE_RESULT ") for line in stdout.splitlines() if line.startswith("AR_WRITE_RESULT ")]
    result = json.loads(markers[-1]) if markers else {}
    plan = json.loads(checked.read_text(encoding="utf-8"))
    if (result.get("origin") != "adopted" or result.get("ledger_verified") is not True
            or result.get("publication_pending") is not True or result.get("new_write_count") != 0
            or result.get("ledger_written") is not bool(plan.get("write"))
            or result.get("adopted_record_count") != len(plan.get("write") or [])
            or result.get("source_workflow_id") != source.id or result.get("request_sha256") != request_sha
            or result.get("candidate_sha256") != response["result_sha256"]
            or result.get("files") != execution._workbook_fingerprints(stage)):
        raise WriteInspectionError("盈亏采用结果与固定候选或实际文件不一致，禁止继续或发布。")
    return {**result, "adoption_candidate": {"path": str(candidate), "sha256": response["result_sha256"]},
            "reason": "已采用原任务经新版本计划核实的盈亏结果；本任务没有再次执行盈亏写入。"}


def require_unstarted_flow(execution) -> None:
    """Do not route an already attempted source flow to the normal writer."""
    link = execution.context.get("ar_linked_recovery")
    _, proof = _read_source(execution, link)
    ledger = execution.execution["steps"].get("write_ledger") or {}
    if ledger.get("origin") != "adopted" or ledger.get("source_workflow_id") != link["source_workflow_id"]:
        raise WriteInspectionError("流转阶段缺少已核实的盈亏采用事实，不能继续。")
    if (proof.payload["failed_phase"] != "write_ledger"
            or proof.payload["flow_result"].get("state") != "not_started_unchanged"
            or proof.payload["flow_result"].get("verified") is not True):
        raise WriteInspectionError("原任务已经尝试流转；必须采用核实结果或明确保留未完成状态，不能再次调用流转写入。")
    _fence(execution, link, proof)
