"""Bind auxiliary AR ledgers to the provenance of immutable material versions."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from .models import FileRecord, WorkflowMaterialSet, WorkflowSession
from .resource_policy import workflow_root


def read_formal_ledger_bundle(db: Session, source: WorkflowSession) -> tuple[dict, FileRecord, dict[str, bytes]]:
    """Read the registered bundle and reconcile it with the actual publication."""
    from .ar_execution_contract import PHASES
    from .ar_publication import publication_manifest

    context = json.loads(source.context_json or "{}")
    execution = context.get("ar_execution") or {}
    if execution.get("completed") != [phase.name for phase in PHASES]:
        raise ValueError("来源材料尚未完成全部核销阶段，必须先恢复原任务的正式登记。")
    publication = publication_manifest(db, source)
    ref = context.get("formal_ledgers") or {}
    record = db.get(FileRecord, str(ref.get("file_id") or ""))
    candidate = ((execution.get("steps") or {}).get("complete_reconciliation") or {}).get("formal_ledger_candidate") or {}
    if (record is None or record.kind != "output" or record.workflow_id != source.id
            or (record.owner_id, record.department_id, record.skill_id)
            != (source.owner_id, source.department_id, source.skill_id)
            or record.sha256 != ref.get("sha256") or record.sha256 != candidate.get("fingerprint")):
        raise ValueError("正式辅助台账的文件登记、完成检查点或业务归属不一致。")
    path = Path(record.stored_path)
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(workflow_root(source.owner_id, source.id).resolve())):
        raise ValueError("正式辅助台账文件缺失或超出原任务目录。")
    limit = 256 * 1024 * 1024
    if path.stat().st_size > limit:
        raise ValueError("正式辅助台账超过 256 MiB 读取上限，不能跳过核查。")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != record.sha256:
        raise ValueError("正式辅助台账实际文件超限或指纹不一致。")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ValueError("正式辅助台账文件无法解析，不能确认台账已登记完成。") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "ar-formal-ledgers-v1" or payload.get("publication") != publication:
        raise ValueError("正式辅助台账与原发布的日期、年度、文件或实际执行结果不一致。")
    json_ledgers, binary_ledgers = payload.get("json_ledgers"), payload.get("binary_ledgers")
    if (not isinstance(json_ledgers, dict) or set(json_ledgers) != {"父回款顺序分配台账.json", "跑批台账.json"}
            or not isinstance(binary_ledgers, dict) or set(binary_ledgers) != {"挂账台账.xlsx"}):
        raise ValueError("正式辅助台账包缺少必要文件或包含未许可文件。")
    for name, collection in (("父回款顺序分配台账.json", "parents"), ("跑批台账.json", "runs")):
        if not isinstance(json_ledgers[name], dict) or not isinstance(json_ledgers[name].get(collection), dict):
            raise ValueError("正式辅助台账的历史记录集合无效。")
    contents = {name: json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                for name, data in json_ledgers.items()}
    for name, data in binary_ledgers.items():
        if not isinstance(data, dict) or not isinstance(data.get("base64"), str):
            raise ValueError("正式挂账台账的内嵌文件格式无效。")
        try:
            content = base64.b64decode(data["base64"], validate=True)
        except ValueError as exc:
            raise ValueError("正式挂账台账的内嵌文件无法解码。") from exc
        if hashlib.sha256(content).hexdigest() != data.get("sha256"):
            raise ValueError("正式挂账台账的内嵌文件指纹不一致。")
        contents[name] = content
    return payload, record, contents


def _confirmed_empty_fetch_dates(
    db: Session, workflow: WorkflowSession, workspace: Path, rows: dict,
) -> set[str]:
    """Recognize the pinned fetcher's empty-day marker, never a processing result."""
    from .fetched_bundle_service import assert_bundle_consumable
    from .workflow_service import FETCHED_DATASET_COUNT_KEYS

    context = json.loads(workflow.context_json or "{}")
    fetched_data = context.get("fetched_data") or {}
    bundle_id = workflow.fetched_bundle_id
    if not bundle_id or fetched_data.get("review_status") != "confirmed":
        return set()
    dates = (
        json.loads(workflow.batch.reconciliation_dates_json)
        if workflow.batch is not None else [workflow.reconciliation_date]
    )
    allowed_fields = {
        "hexiao_date", "first_run_at", "last_run_at", "stage",
        "payment_count", "empty_batch", "note",
    }
    candidates = sorted(day for day, row in rows.items() if (
        day in dates and isinstance(row, dict) and set(row) <= allowed_fields
        and row.get("hexiao_date") == day and row.get("stage") == "classified"
        and row.get("empty_batch") is True
        and type(row.get("payment_count")) is int and row["payment_count"] == 0
        and row.get("note") == "空批：那天没有任何核销"
    ))
    if not candidates:
        return set()
    bundle = assert_bundle_consumable(
        db, bundle_id=bundle_id, owner_id=workflow.owner_id, dates=candidates,
    )
    if (bundle.department_id, bundle.skill_id) != (workflow.department_id, workflow.skill_id):
        raise ValueError("空日期取数包与当前任务的业务范围不一致。")
    export = workspace / "01_智云导出"
    empty_dates = set()
    for member in bundle.files:
        if member.dataset != "summary" or member.reconciliation_date not in candidates:
            continue
        path = export / member.relative_name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("空日期的取数摘要缺失或超出当前工作区。")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != member.sha256:
            raise ValueError("空日期的取数摘要与已确认取数包不一致。")
        summary = json.loads(raw)
        if isinstance(summary, dict) and all(
            type(summary.get(key)) is int and summary[key] == 0
            for key in FETCHED_DATASET_COUNT_KEYS.values()
        ):
            empty_dates.add(member.reconciliation_date)
    return empty_dates


def inherit_formal_ledgers(db: Session, workflow: WorkflowSession, workspace: Path) -> dict:
    material = workflow.material_set
    if material is not None and not material.source_workflow_id and material.parent_set_id:
        parent_id = material.parent_set_id
        seen = {material.id}
        while parent_id:
            if parent_id in seen:
                raise ValueError("业务材料历史存在循环引用，无法核对辅助台账来源")
            seen.add(parent_id)
            parent = db.get(WorkflowMaterialSet, parent_id)
            if parent is None or (parent.owner_id, parent.department_id, parent.skill_id) != (
                workflow.owner_id, workflow.department_id, workflow.skill_id,
            ):
                raise ValueError("业务材料父版本不存在或不属于当前业务范围")
            source = db.get(WorkflowSession, parent.source_workflow_id) if parent.source_workflow_id else None
            if parent.source_workflow_id and (source is None or (
                source.owner_id, source.department_id, source.skill_id,
            ) != (workflow.owner_id, workflow.department_id, workflow.skill_id)):
                raise ValueError("父材料引用的来源任务缺失或业务范围不一致，不能按旧版空历史处理")
            if source is not None:
                raise ValueError("人工替换的材料存在核销历史，但辅助台账与当前工作簿的对应关系未核实；请先绑定对应历史台账，不能按空历史执行。")
            parent_id = parent.parent_set_id
        return {"mode": "legacy_material", "parent_set_id": material.parent_set_id}
    if material is None or not material.source_workflow_id:
        return {"mode": "initial_material"}
    source = db.get(WorkflowSession, material.source_workflow_id)
    if source is None or (source.owner_id, source.department_id, source.skill_id) != (
        workflow.owner_id, workflow.department_id, workflow.skill_id,
    ):
        raise ValueError("业务材料的辅助台账来源不存在或权限不一致")
    context = json.loads(source.context_json or "{}")
    if not context.get("ar_execution"):
        raise ValueError(
            "当前材料来自旧流程核销结果，但旧父回款分配台账尚未与该材料建立可验证绑定；"
            "已停止核销，请先迁移并核实该材料的历史分配台账，不能只沿用已写工作簿按空历史执行。"
        )
    payload, record, contents = read_formal_ledger_bundle(db, source)
    publication = payload.get("publication") or {}
    expected = sorted((item.role, item.year, item.file_id, item.sha256) for item in material.files)
    published = sorted((item["role"], item["year"], item["file_id"], item["sha256"]) for item in publication["files"])
    if expected != published:
        raise ValueError("辅助台账对应的发布文件、年度或指纹与当前所选材料不一致")
    json_ledgers = payload["json_ledgers"]
    folder = workspace / "03_台账"
    folder.mkdir(exist_ok=True)
    local_batch = folder / "跑批台账.json"
    if local_batch.is_file():
        fetched = json.loads(local_batch.read_text(encoding="utf-8"))
        inherited = json_ledgers["跑批台账.json"]
        pending = {
            day: row for day, row in (fetched.get("runs") or {}).items()
            if row != inherited.get("runs", {}).get(day) and (
                not isinstance(row, dict) or row.get("stage") != "fetched"
            )
        }
        empty_dates = _confirmed_empty_fetch_dates(db, workflow, workspace, pending) if pending else set()
        for day in pending:
            if day not in empty_dates:
                raise ValueError("当前任务已存在取数之后的跑批记录，禁止替换正式台账")
        current = (fetched.get("runs") or {}).get(workflow.reconciliation_date)
        if current and workflow.reconciliation_date not in inherited.get("runs", {}):
            # Initialization only inherits this date's fetch fact. Later dates
            # remain pending in the platform even if the fetcher called them done.
            if workflow.reconciliation_date in empty_dates:
                current = {**current, "stage": "fetched"}
            inherited.setdefault("runs", {})[workflow.reconciliation_date] = current
        contents["跑批台账.json"] = json.dumps(inherited, ensure_ascii=False, indent=2).encode("utf-8")
    for name, content in contents.items():
        target = folder / name
        if name != "跑批台账.json" and target.exists() and target.read_bytes() != content:
            raise ValueError("当前任务已有不同的辅助台账，禁止覆盖")
    for name, content in contents.items():
        (folder / name).write_bytes(content)
    return {"mode": "published_bundle", "source_workflow_id": source.id,
            "file_id": record.id, "sha256": record.sha256}
