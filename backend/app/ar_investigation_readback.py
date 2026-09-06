"""Recheck an investigation against current files before planning linked recovery.

This reader never completes a phase or authorizes a write. Its live guard must
be checked again after taking the execution lock; a saved summary is not proof.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .ar_execution_contract import CONTRACT_VERSION, INVESTIGATION_ACTION, next_phase
from .ar_process_inspection import inspect_process_evidence
from .ar_write_inspection import EvidenceReader, HASH, MAX_FILES, MAX_TOTAL_BYTES, WriteInspectionError, _workbook_names, _workspace

INPUT_VERSION = "ar-investigation-inputs-v1"
ASSESSMENT_VERSION = "ar-write-recovery-assessment-v1"


@dataclass
class InvestigationReadback:
    payload: dict
    reader: EvidenceReader
    fingerprint: str

    def check_unchanged(self) -> None:
        self.reader.finish()


def read_investigation(workflow, action, reference: dict) -> InvestigationReadback:
    """Read full evidence outside the claim lock, with no display cache."""
    context = json.loads(workflow.context_json or "{}")
    state, failure = context.get("ar_execution") or {}, context.get("ar_failure") or {}
    phase = next_phase(state.get("completed") or [])
    failed = next((item for item in workflow.actions if item.id == failure.get("action_id")), None)
    request = json.loads(action.input_json or "{}")
    if (state.get("schema_version") != CONTRACT_VERSION or workflow.state != "failed"
            or phase is None or phase.name not in {"write_ledger", "write_receipt_flow"}
            or action.name != INVESTIGATION_ACTION or action.workflow_id != workflow.id
            or action.state not in {"running", "succeeded"}
            or request.get("failed_action_id") != failure.get("action_id")
            or failed is None or failed.state != "failed" or failed.finished_at is None
            or failed.name != f"ar_{phase.name}" or failed.workflow_id != workflow.id
            or any(item.state in {"queued", "running"} and item.id != action.id for item in workflow.actions)
            or failure.get("phase") != phase.name
            or state.get("skill_hash") != workflow.skill_hash
            or state.get("ledger_years") != context.get("ledger_years")
            or state.get("reconciliation_date") != workflow.reconciliation_date):
        raise WriteInspectionError("调查记录与原失败写入阶段、日期或固定版本不一致。")
    if action.state == "succeeded" and (json.loads(action.result_json or "{}").get("report") != reference or not action.finished_at):
        raise WriteInspectionError("已完成调查的报告引用与原动作登记不一致。")
    workspace = _workspace(workflow, context)
    reader = EvidenceReader(workspace)
    staged = (state.get("steps") or {}).get("stage_reconciliation") or {}
    stage = reader.path(staged.get("staging_workspace"))
    if stage.parent != workspace / "03_写入暂存区" or not stage.is_dir():
        raise WriteInspectionError("原暂存目录缺失或与固定执行不一致。")
    expected_report = stage / "execution-investigations" / action.id.replace("-", "") / "result.json"
    report = reader.path(reference.get("path"))
    if report != expected_report:
        raise WriteInspectionError("调查报告不属于本次独立调查动作。")
    payload, fingerprint = reader.read(report, document=True)
    if fingerprint != reference.get("sha256"):
        raise WriteInspectionError("调查报告实际文件与登记指纹不一致。")
    # Original capture allowed 256 MiB of inputs, independent of the 16 MiB
    # report. Do not reject that same valid set by counting the report twice.
    reader.remaining = MAX_TOTAL_BYTES
    if (payload.get("schema_version") != "ar-write-investigation-v1"
            or payload.get("workflow_id") != workflow.id
            or payload.get("attempt") != action.id.replace("-", "")
            or payload.get("reconciliation_date") != workflow.reconciliation_date
            or payload.get("material_set_id") != state.get("material_set_id")
            or payload.get("failed_phase") != phase.name
            or payload.get("authorizes_resume") is not False or payload.get("publication_verified") is not False):
        raise WriteInspectionError("调查报告的业务绑定或用途声明无效，不能作为恢复依据。")
    if payload.get("input_contract_version") != INPUT_VERSION:
        raise WriteInspectionError("该调查未记录完整输入指纹，只能查看历史结果，不能用于创建关联恢复任务。")
    if payload.get("inputs_unchanged") is not True:
        raise WriteInspectionError("调查当时原输入已经变化，不能使用该报告处理当前写入结果。")
    manifest = staged.get("manifest") or {}
    files, protected = manifest.get("files"), manifest.get("protected_inputs")
    inputs = payload.get("input_files")
    if (not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES
            or not isinstance(protected, dict) or not 1 <= len(protected) <= MAX_FILES
            or not isinstance(inputs, dict) or set(inputs) != {"baseline", "staging"}):
        raise WriteInspectionError("调查输入或原暂存清单缺少完整文件集合。")
    expected_sets = {"baseline": set(files), "staging": set(files) | set(protected) | {"execution-manifest.json"}}
    documents = {}
    for scope, root in (("baseline", workspace), ("staging", stage)):
        entries = inputs[scope]
        if not isinstance(entries, dict) or set(entries) != expected_sets[scope]:
            raise WriteInspectionError("调查输入指纹未完整覆盖原材料、实际工作簿和受保护计划。")
        if _workbook_names(reader, root / "02_我的表副本") != set(files):
            raise WriteInspectionError("调查后工作簿集合已经变化，不能采用旧调查结果。")
        for name, item in entries.items():
            relative = PurePosixPath(name)
            if (relative.is_absolute() or relative.as_posix() != name
                    or any(part in {"..", "."} or ":" in part or "\\" in part for part in relative.parts)
                    or not isinstance(item, dict) or type(item.get("size")) is not int
                    or item["size"] < 0 or not isinstance(item.get("sha256"), str)
                    or not HASH.fullmatch(item["sha256"])):
                raise WriteInspectionError("调查输入指纹包含非法路径、大小或哈希。")
            path = reader.path(root / name)
            if path.stat().st_size != item["size"]:
                raise WriteInspectionError("调查后输入文件大小已经变化，必须重新核查当前文件。")
            document = scope == "staging" and name == "execution-manifest.json"
            value, actual = reader.read(path, document=document)
            if actual != item["sha256"]:
                raise WriteInspectionError("调查后输入文件内容已经变化，不能使用旧报告放行恢复。")
            if scope == "baseline" and actual != files[name]:
                raise WriteInspectionError("原材料与写前登记指纹不一致。")
            if scope == "staging" and name in protected and actual != protected[name]:
                raise WriteInspectionError("受保护首次结果或校验计划与原登记不一致。")
            if document:
                documents[name] = value
    if (documents.get("execution-manifest.json") != manifest
            or payload.get("manifest_sha256") != inputs["staging"]["execution-manifest.json"]["sha256"]
            or payload.get("plan_sha256") != manifest.get("staged_plan_fingerprint")):
        raise WriteInspectionError("调查报告、暂存清单和校验计划未绑定同一执行。")
    original_checked = reader.path(context.get("checked_plan"))
    if original_checked.is_relative_to(stage):
        raise WriteInspectionError("原校验计划错误引用了写入暂存内的副本。")
    _, original_fingerprint = reader.read(original_checked)
    if original_fingerprint != context.get("plan_fingerprint") or original_fingerprint != manifest.get("initial_plan_fingerprint"):
        raise WriteInspectionError("原校验计划与任务或暂存登记不一致。")
    ledger_files = {str(year): reader.path(path).relative_to(workspace).as_posix()
                    for year, path in (context.get("ledger_years") or {}).items()}
    flow_file = reader.path(context.get("flow_file")).relative_to(workspace).as_posix()
    if (not ledger_files or payload.get("ledger_files") != ledger_files or payload.get("flow_file") != flow_file
            or (set(ledger_files.values()) | {flow_file}) - set(files)
            or len(set(ledger_files.values())) != len(ledger_files) or flow_file in ledger_files.values()):
        raise WriteInspectionError("调查年度及流转文件对应关系与原任务不一致。")
    ledgers, flow, others = payload.get("ledger_results"), payload.get("flow_result"), payload.get("other_workbooks")
    if (not isinstance(ledgers, dict) or set(ledgers) != set(ledger_files)
            or not isinstance(flow, dict) or not isinstance(others, dict)
            or set(others) != set(files) - set(ledger_files.values()) - {flow_file}
            or any(not isinstance(item, dict) for item in [*ledgers.values(), *others.values()])):
        raise WriteInspectionError("调查的盈亏、流转或非目标工作簿结果覆盖不完整。")
    all_results = [*ledgers.values(), flow, *others.values()]
    if (any(type(item.get("verified")) is not bool for item in all_results)
            or payload.get("business_files_match_expected") is not all(item["verified"] for item in all_results)):
        raise WriteInspectionError("调查的总体结论与逐文件核验状态不一致。")
    for relative, result in [*((ledger_files[year], entry) for year, entry in ledgers.items()), (flow_file, flow)]:
        if (result.get("verified") is True or result.get("state") == "baseline_retained") and (
            result.get("baseline_sha256") != inputs["baseline"][relative]["sha256"]
            or result.get("actual_sha256") != inputs["staging"][relative]["sha256"]
        ):
            raise WriteInspectionError("调查结论与实际比较的工作簿指纹不一致。")
    reader.finish()
    return InvestigationReadback(payload, reader, hashlib.sha256(json.dumps(
        {"report_sha256": fingerprint, "input_files": inputs}, sort_keys=True, ensure_ascii=False).encode()).hexdigest())


def assess_write_result(workflow, payload: dict, input_fingerprint: str) -> dict:
    """Describe confirmed work and the remaining checks, not permission to run."""
    context = json.loads(workflow.context_json or "{}")
    failure = context.get("ar_failure") or {}
    failed = next((item for item in workflow.actions if item.id == failure.get("action_id")), None)
    base = {"schema_version": ASSESSMENT_VERSION, "inputs_current": True,
            "input_fingerprint": input_fingerprint, "authorizes_resume": False,
            "ledger_confirmed": False, "flow_confirmed": False, "suggested_next_phase": ""}
    ledger_ok = all(item.get("verified") is True and item.get("rows_verified") is True
                    and item.get("package_verified") is True for item in payload["ledger_results"].values())
    other_ok = all(item.get("verified") is True for item in payload["other_workbooks"].values())
    flow = payload["flow_result"]
    if not ledger_ok or not other_ok:
        return {**base, "code": "business_result_unconfirmed",
                "message": "盈亏或非目标工作簿仍有未核实差异，不能将原写入登记为完成，也不能从头重写。"}
    base["ledger_confirmed"] = True
    if failure.get("phase") == "write_ledger" and flow.get("verified") is True and flow.get("state") == "not_started_unchanged":
        base.update(code="ledger_confirmed_flow_pending", suggested_next_phase="write_receipt_flow",
                    message="盈亏实际结果已独立核实，流转尚未开始；关联恢复应保留盈亏结果，只处理后续流转与复核。")
    elif failure.get("phase") == "write_receipt_flow" and flow.get("verified") is True and flow.get("state") == "matches_expected":
        base.update(code="writes_confirmed_review_pending", flow_confirmed=True, suggested_next_phase="verify_reconciliation",
                    message="盈亏和流转实际结果均已独立核实；关联恢复应从写后复核继续，不能重复两项写入。")
    elif (failure.get("phase") == "write_receipt_flow" and flow.get("state") == "baseline_retained"
          and flow.get("baseline_sha256") == flow.get("actual_sha256")):
        base.update(code="ledger_confirmed_flow_baseline", suggested_next_phase="verify_reconciliation",
                    message="盈亏结果已核实，流转仍是写前副本；需在关联恢复中明确保留流转未完成状态，不能重做盈亏或将流转标成成功。")
    else:
        return {**base, "code": "flow_result_unconfirmed",
                "message": "流转实际结果尚未核实，不能采用不明改动，也不能重复盈亏写入。"}
    process = inspect_process_evidence(workflow, failed, failure) if failed is not None else {}
    base["process_facts_verified"] = process.get("verified") is True and failure.get("process_exit_confirmed") is True
    base["message"] += (" 原脚本停止事实仍未完整核实。" if not base["process_facts_verified"] else " 已核对原脚本退出记录。")
    base["message"] += " 仍须核查外部应用状态、当前材料、新 Skill 兼容性、权限及恢复计划；本结论不授权执行。"
    return base
