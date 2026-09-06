"""Read an AR publication from its immutable material and file records."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from .ar_execution_contract import CONTRACT_VERSION, PHASES
from .models import FileRecord, WorkflowMaterialSet, WorkflowSession
from .resource_policy import workflow_root
from .workflow_material_service import ANNUAL_LEDGER_ROLE, RECEIPT_FLOW_ROLE


@dataclass(frozen=True)
class PublishedReport:
    path: Path
    sha256: str


class PublishedReportError(ValueError):
    """A fixed, safe explanation for an unavailable registered report."""


def published_report(db: Session, workflow: WorkflowSession, name: str) -> PublishedReport:
    """Locate a published report; callers hash the same bytes they consume."""
    token = workflow.reconciliation_date.replace("-", "")
    if name not in {f"核销日清_{token}.xlsx", f"最终核销结果_{token}.json"}:
        raise PublishedReportError("请求的文件不是本日许可的正式核销报告。")
    context = json.loads(workflow.context_json or "{}")
    execution = context.get("ar_execution") or {}
    completed = execution.get("completed") or []
    phases = [phase.name for phase in PHASES]
    if (execution.get("schema_version") != CONTRACT_VERSION
            or execution.get("publication") != "verified" or completed not in (phases[:-1], phases)
            or execution.get("reconciliation_date") != workflow.reconciliation_date):
        raise PublishedReportError("本日核销报告尚无完整的发布记录，不能按正式结果读取。")
    publication = (execution.get("steps") or {}).get("publish_reconciliation") or {}
    candidates = [item for item in publication.get("artifacts") or []
                  if isinstance(item, dict) and item.get("name") == name]
    if len(candidates) != 1:
        raise PublishedReportError("本日缺少唯一的已发布核销报告，不能用暂存报告代替。")
    artifact = candidates[0]
    record = db.get(FileRecord, str(artifact.get("file_id") or ""))
    if (record is None or record.kind != "output" or record.original_name != name
            or record.workflow_id != workflow.id
            or (record.owner_id, record.department_id, record.skill_id)
            != (workflow.owner_id, workflow.department_id, workflow.skill_id)
            or record.sha256 != artifact.get("sha256")):
        raise PublishedReportError("已发布核销报告的登记、名称、业务归属或指纹不一致。")
    path = Path(record.stored_path)
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise PublishedReportError("已发布核销报告缺失或超出原任务目录。")
    return PublishedReport(path.resolve(), record.sha256)


def publication_manifest(db: Session, workflow: WorkflowSession) -> dict:
    """Verify a historical publication without requiring it to remain current.

    Publishing still requires the current-material guard in the executor. This
    readback is also used by subsequent dates and historical material restores.
    """
    context = json.loads(workflow.context_json or "{}")
    state = context.get("ar_execution") or {}
    completed = state.get("completed") or []
    prefix = [phase.name for phase in PHASES]
    if (state.get("schema_version") != CONTRACT_VERSION
            or completed not in (prefix[:-1], prefix)
            or state.get("publication") != "verified"
            or state.get("reconciliation_date") != workflow.reconciliation_date
            or state.get("skill_hash") != workflow.skill_hash):
        raise ValueError("核销阶段、日期或版本与已发布记录不一致，不能确认发布结果。")
    steps = state.get("steps") or {}
    published = steps.get("publish_reconciliation") or {}
    material = db.get(WorkflowMaterialSet, str(published.get("material_set_id") or ""))
    if (material is None or material.id != workflow.material_set_id
            or material.version != published.get("material_version")
            or material.source_workflow_id != workflow.id
            or material.parent_set_id != state.get("material_set_id")
            or (material.owner_id, material.department_id, material.skill_id)
            != (workflow.owner_id, workflow.department_id, workflow.skill_id)):
        raise ValueError("已发布材料的版本、来源任务或业务范围不一致，禁止重复发布或写入。")
    members = sorted(material.files, key=lambda item: (item.role, item.year))
    annual = [item for item in members if item.role == ANNUAL_LEDGER_ROLE]
    flow = [item for item in members if item.role == RECEIPT_FLOW_ROLE]
    if (not 1 <= len(annual) <= 32 or len(flow) != 1 or len(members) != len(annual) + 1
            or len({item.file_id for item in members}) != len(members)
            or len({item.year for item in annual}) != len(annual)
            or any(type(item.year) is not int or not 2000 <= item.year <= 2099 for item in annual)
            or flow[0].year != 0):
        raise ValueError("已发布材料缺少唯一流转表或完整年度盈亏文件，不能登记完成。")
    bindings = published.get("next_files")
    if not isinstance(bindings, dict) or set(bindings) != {ANNUAL_LEDGER_ROLE, RECEIPT_FLOW_ROLE}:
        raise ValueError("发布检查点的工作簿用途不完整，须核查原发布记录。")
    expected = {(item.role, item.year, item.file_id, item.sha256) for item in members}
    recorded = []
    for role, entries in bindings.items():
        if not isinstance(entries, list):
            raise ValueError("发布检查点的文件引用格式无效。")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("发布检查点的文件引用格式无效。")
            year, file_id, digest = entry.get("year"), entry.get("file_id"), entry.get("sha256")
            if (not isinstance(file_id, str) or not file_id or not isinstance(digest, str)
                    or (role == ANNUAL_LEDGER_ROLE and type(year) is not int)
                    or (role == RECEIPT_FLOW_ROLE and year is not None and (type(year) is not int or year != 0))):
                raise ValueError("发布检查点的年度、文件标识或指纹格式无效。")
            recorded.append((role, year if year is not None else 0, file_id, digest))
    if len(recorded) != len(members) or set(recorded) != expected:
        raise ValueError("发布检查点与材料版本的文件、年度或指纹不一致。")
    root = workflow_root(workflow.owner_id, workflow.id).resolve(strict=True)
    files = []
    for member in members:
        record = db.get(FileRecord, member.file_id)
        if (record is None or record.kind != "output" or record.workflow_id != workflow.id
                or (record.owner_id, record.department_id, record.skill_id)
                != (workflow.owner_id, workflow.department_id, workflow.skill_id)
                or record.sha256 != member.sha256):
            raise ValueError("已发布工作簿的登记、归属或指纹不一致。")
        path = Path(record.stored_path)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("已发布工作簿缺失或超出原任务目录，不能确认完成。")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != record.sha256:
            raise ValueError("已发布工作簿的实际文件指纹不一致，须核查现有结果，禁止重新写表。")
        files.append({"role": member.role, "year": member.year,
                      "file_id": record.id, "sha256": record.sha256})
    ledger_written = (steps.get("write_ledger") or {}).get("ledger_written")
    flow_written = (steps.get("write_receipt_flow") or {}).get("flow_written")
    if type(ledger_written) is not bool or type(flow_written) is not bool:
        raise ValueError("已发布材料缺少盈亏或流转的实际执行结果，不能登记完成。")
    return {"schema_version": "ar-publication-v1", "workflow_id": workflow.id,
            "reconciliation_date": workflow.reconciliation_date,
            "material_set_id": material.id, "material_version": material.version, "files": files,
            "written": {"盈亏": ledger_written, "流转": flow_written}}
