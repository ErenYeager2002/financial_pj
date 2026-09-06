"""Read failed write evidence without executing Skill code or changing workbooks.

This is an investigation, never a replacement for independent row/package
verification or a permit to repeat a financial write. Candidate receipt contents
are not promoted to an authoritative completed phase.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from .ar_execution_contract import CONTRACT_VERSION, next_phase
from .resource_policy import workflow_root

MAX_FILES = 32
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}")
_CACHE = collections.OrderedDict()
_CACHE_LOCK = threading.Lock()
_IN_FLIGHT = set()
MAX_CACHED_INSPECTIONS = 8
CACHE_SECONDS = 30


class WriteInspectionError(ValueError):
    """Only fixed, non-sensitive reasons may be returned to a user."""


class EvidenceReader:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        self.remaining = MAX_TOTAL_BYTES
        self.observed = {}
        self.watched = {}

    def path(self, raw: object) -> Path:
        if not isinstance(raw, (str, Path)) or not str(raw):
            raise WriteInspectionError("核查文件引用缺失。")
        path = Path(raw)
        if not path.is_absolute():
            path = self.root / path
        if not path.is_relative_to(self.root) or ".." in path.parts:
            raise WriteInspectionError("核查文件引用超出当前任务。")
        for part in (path, *path.parents):
            if part == self.root:
                break
            if part.is_symlink():
                raise WriteInspectionError("核查文件路径包含符号链接。")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise WriteInspectionError("核查文件不属于当前任务。")
        self.watch(resolved)
        return resolved

    @staticmethod
    def stamp(path: Path) -> tuple:
        stat = path.lstat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def watch(self, path: Path) -> None:
        try:
            stamp = self.stamp(path)
        except FileNotFoundError:
            stamp = None
        previous = self.watched.setdefault(str(path), stamp)
        if previous != stamp:
            raise WriteInspectionError("核查期间文件发生变化，结果不能作为恢复依据。")

    def read(self, raw: object, *, document: bool = False) -> tuple[dict | None, str]:
        path = self.path(raw)
        if not path.is_file():
            raise WriteInspectionError("核查所需文件缺失或不是普通文件。")
        before = self.stamp(path)
        limit = min(self.remaining, MAX_JSON_BYTES if document else self.remaining)
        if before[2] > limit:
            raise WriteInspectionError("核查材料超过读取上限，未忽略剩余文件。")
        digest, chunks, size = hashlib.sha256(), [], 0
        with path.open("rb") as handle:
            while chunk := handle.read(min(1024 * 1024, limit - size + 1)):
                size += len(chunk)
                if size > limit:
                    raise WriteInspectionError("核查材料超过读取上限，未忽略剩余文件。")
                digest.update(chunk)
                if document:
                    chunks.append(chunk)
        self.remaining -= size
        if self.stamp(path) != before:
            raise WriteInspectionError("核查期间文件发生变化，结果不能作为恢复依据。")
        self.observed[str(path)] = (before, digest.hexdigest())
        value = json.loads(b"".join(chunks)) if document else None
        if document and not isinstance(value, dict):
            raise WriteInspectionError("核查文档不是有效的对象。")
        return value, digest.hexdigest()

    def finish(self) -> list[str]:
        if (not _snapshot_current(self.watched)
                or any(self.stamp(Path(path)) != fact[0] for path, fact in self.observed.items())):
            raise WriteInspectionError("核查期间文件发生变化，结果不能作为恢复依据。")
        return [fact[1] for _, fact in sorted(self.observed.items())]


def _fingerprints(value: object) -> dict:
    if (not isinstance(value, dict) or not value or len(value) > MAX_FILES
            or any(not isinstance(key, str) or not isinstance(sha, str) or not HASH.fullmatch(sha)
                   for key, sha in value.items())):
        raise WriteInspectionError("已登记工作簿指纹缺失、无效或超过数量上限。")
    return value


def _workspace(workflow, context: dict) -> Path:
    primary = workflow
    if workflow.batch_id:
        batch = workflow.batch
        if batch is None or not batch.workflows:
            raise WriteInspectionError("缺少原批次及首日工作区记录。")
        primary = min(batch.workflows, key=lambda item: item.batch_sequence)
        if any(getattr(primary, key) != getattr(workflow, key) for key in (
            "owner_id", "department_id", "skill_id", "skill_hash", "execution_mode",
        )):
            raise WriteInspectionError("批次固定输入身份不一致。")
    root = workflow_root(primary.owner_id, primary.id)
    reader = EvidenceReader(root)
    workspace = reader.path(context.get("workspace"))
    if workspace == reader.root or not workspace.is_dir():
        raise WriteInspectionError("原核销工作区缺失或引用无效。")
    return workspace


def _workbook_names(reader: EvidenceReader, folder: Path) -> set[str]:
    reader.path(folder)
    names = set()
    for path in folder.glob("*.xls*"):
        if "便携版" in path.name or path.name.startswith("."):
            continue
        reader.path(path)
        if not path.is_file():
            raise WriteInspectionError("工作簿集合中存在非文件内容。")
        names.add(path.relative_to(folder.parent).as_posix())
        if len(names) > MAX_FILES:
            raise WriteInspectionError("工作簿数量超过核查上限。")
    return names


def _receipt(reader: EvidenceReader, stage: Path, day: str, year: str, writes: list) -> dict:
    label = f"{year} 年盈亏凭据"
    path = reader.path(stage / "04_产出" / f"盈亏执行_{day.replace('-', '')}_{year}.json")
    if not path.exists():
        return {"label": label, "state": "missing" if writes else "not_required",
                "message": f"{label}缺失，计划待写 {len(writes)} 条。" if writes else f"{label}无需生成，固定计划无待写记录。"}
    try:
        receipt, _ = reader.read(path, document=True)
    except (OSError, ValueError, TypeError):
        return {"label": label, "state": "unreadable",
                "message": f"{label}无法完整读取或解析，不能核对案例覆盖。"}
    items = receipt.get("items")
    valid = (receipt.get("verified") is True and receipt.get("hexiao_date") == day
             and isinstance(items, list) and all(isinstance(item, dict) for item in items)
             and collections.Counter(str(item.get("case_id") or "") for item in items)
             == collections.Counter(str(item.get("case_id") or "") for item in writes))
    return {"label": label, "state": "candidate_consistent" if valid else "candidate_mismatch",
            "message": (f"{label}中的日期和 {len(writes)} 条案例覆盖与固定计划一致；尚未独立核对实际单元格。"
                        if valid else f"{label}的日期、回读标记或案例覆盖与固定计划不一致。")}


def _inspect_write_evidence(workflow, action) -> tuple[dict, dict]:
    result = {"state": "unconfirmed", "files": [], "receipts": [], "verified": False,
              "message": "写入结果尚未独立核实。"}
    observed = []
    reader = None
    try:
        context = json.loads(workflow.context_json or "{}")
        state = context.get("ar_execution") or {}
        phase = next_phase(state.get("completed") or [])
        if (state.get("schema_version") != CONTRACT_VERSION
                or state.get("reconciliation_date") != workflow.reconciliation_date
                or state.get("skill_hash") != workflow.skill_hash or phase is None
                or phase.name not in {"write_ledger", "write_receipt_flow"}
                or action.workflow_id != workflow.id or action.name != f"ar_{phase.name}"
                or action.state != "failed" or not action.finished_at or workflow.state != "failed"
                or any(item.state in {"queued", "running"} for item in workflow.actions)):
            raise WriteInspectionError("任务状态或失败阶段不满足只读写入核查条件。")
        workspace = _workspace(workflow, context)
        reader = EvidenceReader(workspace)
        steps = state.get("steps") or {}
        staged = steps.get("stage_reconciliation") or {}
        stage = reader.path(staged.get("staging_workspace"))
        parent = workspace / "03_写入暂存区"
        if not stage.is_dir() or stage.parent != parent:
            raise WriteInspectionError("暂存工作区缺失或不属于原写入任务。")
        manifest, _ = reader.read(stage / "execution-manifest.json", document=True)
        if (manifest != staged.get("manifest") or manifest.get("schema_version") != CONTRACT_VERSION
                or manifest.get("workflow_id") != workflow.id
                or manifest.get("material_set_id") != state.get("material_set_id")
                or manifest.get("initial_plan_fingerprint") != context.get("plan_fingerprint")):
            raise WriteInspectionError("暂存清单与原任务、材料或计划登记不一致。")
        _, original_plan_sha = reader.read(context.get("checked_plan"))
        if original_plan_sha != context.get("plan_fingerprint"):
            raise WriteInspectionError("原校验计划已变化，不能解释当前文件改动。")
        checked = reader.path(manifest.get("checked_plan"))
        if not checked.is_relative_to(stage):
            raise WriteInspectionError("暂存计划引用超出暂存工作区。")
        protected = _fingerprints(manifest.get("protected_inputs"))
        if protected.get(checked.relative_to(stage).as_posix()) != manifest.get("staged_plan_fingerprint"):
            raise WriteInspectionError("暂存计划缺少一致的保护指纹。")
        for relative, expected in protected.items():
            path = reader.path(stage / relative)
            if not path.is_relative_to(stage) or reader.read(path)[1] != expected:
                raise WriteInspectionError("首次结果、计划或日清与固定指纹不一致。")
        plan, plan_sha = reader.read(checked, document=True)
        if plan_sha != manifest.get("staged_plan_fingerprint") or plan.get("hexiao_date") != workflow.reconciliation_date:
            raise WriteInspectionError("暂存计划的日期或指纹与原任务不一致。")
        baseline = _fingerprints(manifest.get("files"))
        checkpoint = (baseline if phase.name == "write_ledger"
                      else _fingerprints((steps.get("write_ledger") or {}).get("files")))
        if (set(checkpoint) != set(baseline)
                or _workbook_names(reader, workspace / "02_我的表副本") != set(baseline)
                or _workbook_names(reader, stage / "02_我的表副本") != set(baseline)):
            raise WriteInspectionError("原材料、暂存文件或阶段登记的工作簿集合不一致。")
        roles = {}
        years = context.get("ledger_years")
        if not isinstance(years, dict) or not years or len(years) > MAX_FILES:
            raise WriteInspectionError("原任务未记录年度盈亏文件对应关系。")
        for year, raw in years.items():
            if not re.fullmatch(r"[0-9]{4}", str(year)):
                raise WriteInspectionError("原任务的盈亏年度无效。")
            relative = reader.path(raw).relative_to(workspace).as_posix()
            if relative in roles:
                raise WriteInspectionError("多个盈亏年度引用同一文件，不能区分核查结果。")
            roles[relative] = f"{year} 年盈亏"
        flow = reader.path(context.get("flow_file")).relative_to(workspace).as_posix()
        if flow in roles or not set(roles).issubset(baseline) or flow not in baseline:
            raise WriteInspectionError("年度盈亏或流转引用与原工作簿清单不一致。")
        roles[flow] = "到账流转"
        for index, (relative, before) in enumerate(sorted(baseline.items())):
            label = roles.get(relative, f"其他工作簿 {index + 1}")
            original = reader.read(workspace / relative)[1]
            actual = reader.read(stage / relative)[1]
            if original != before:
                code, message = "baseline_changed", "原副本已偏离写前指纹，缺少可信比较基准。"
            elif actual == before:
                code, message = "unchanged", "当前暂存文件与写前副本完全一致；不能据此推断原执行从未写入。"
            elif actual == checkpoint[relative]:
                code, message = "matches_checkpoint", "当前文件与已登记的上一阶段结果一致。"
            else:
                code, message = "changed_unconfirmed", "当前文件已变化，且不匹配已登记阶段结果，尚不能判断完整或部分写入。"
            result["files"].append({"label": label, "state": code, "message": f"{label}：{message}"})
        writes = plan.get("write")
        if (not isinstance(writes, list) or any(not isinstance(item, dict) or not item.get("case_id")
                                               or str(item.get("ledger_year")) not in years for item in writes)):
            raise WriteInspectionError("固定计划缺少有效案例或年度引用。")
        for year in sorted(years):
            result["receipts"].append(_receipt(reader, stage, workflow.reconciliation_date, year,
                                             [item for item in writes if str(item["ledger_year"]) == year]))
        flow_result = reader.path(stage / "04_产出" / "流转阶段执行结果.json")
        if flow_result.exists():
            try:
                candidate, _ = reader.read(flow_result, document=True)
                valid = candidate.get("schema_version") == "ar-flow-result-v1" and type(candidate.get("flow_written")) is bool
                flow_receipt = {"label": "流转执行记录", "state": "candidate_present" if valid else "candidate_mismatch",
                                "message": "流转执行记录已读取，尚未独立核对文件改动。" if valid else "流转执行记录格式无效。"}
            except (OSError, ValueError, TypeError):
                flow_receipt = {"label": "流转执行记录", "state": "unreadable",
                                "message": "流转执行记录无法完整读取或解析，不能确认流转结果；盈亏文件和凭据核查另列。"}
            result["receipts"].append(flow_receipt)
        else:
            result["receipts"].append({"label": "流转执行记录", "state": "missing" if phase.name == "write_receipt_flow" else "not_started",
                                       "message": "流转执行记录缺失。" if phase.name == "write_receipt_flow" else "流程尚未进入流转阶段。"})
        observed = reader.finish()
        result.update(state="inspected", message="已只读比较写前、暂存与已登记阶段文件；各份凭据能否核对案例覆盖分别列明。尚未完成独立单元格和全工作簿复核，禁止重复写入或据此发布。")
    except WriteInspectionError as exc:
        result.update(state="unconfirmed", message=str(exc))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result.update(state="unconfirmed", message="写入核查材料缺失、格式无效或无法读取；尚不能确定实际写入结果。")
    if result["state"] != "inspected":
        result["files"] = []
        result["receipts"] = []
    result["fingerprint"] = hashlib.sha256(json.dumps(
        {"summary": result, "observed": observed}, ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return result, reader.watched if reader else {}


def _snapshot_current(watched: dict) -> bool:
    try:
        for raw, expected in watched.items():
            try:
                actual = EvidenceReader.stamp(Path(raw))
            except FileNotFoundError:
                actual = None
            if actual != expected:
                return False
    except OSError:
        return False
    return True


def inspect_write_evidence(workflow, action) -> dict:
    """A bounded display snapshot, never read under the recovery claim lock.

    File identity changes invalidate the cache; expiry limits stale display even
    on filesystems with weak timestamps. No cached result authorizes recovery.
    At most two investigations run together; matching requests do not duplicate IO.
    """
    key = (workflow.owner_id, workflow.department_id, workflow.id, workflow.state,
           workflow.skill_hash, workflow.reconciliation_date, action.id, action.state,
           action.attempt_count, str(action.finished_at),
           hashlib.sha256((workflow.context_json or "{}").encode("utf-8")).hexdigest())
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and entry[0] > time.monotonic() and _snapshot_current(entry[1]):
            _CACHE.move_to_end(key)
            return json.loads(entry[2])
        if key in _IN_FLIGHT or len(_IN_FLIGHT) >= 2:
            return {"state": "busy", "verified": False, "files": [], "receipts": [],
                    "message": "只读写入核查正在进行，请稍后重新读取执行记录；当前不允许重复写入。",
                    "fingerprint": hashlib.sha256(b"write-inspection-busy").hexdigest()}
        _IN_FLIGHT.add(key)
    try:
        result, watched = _inspect_write_evidence(workflow, action)
        if watched and _snapshot_current(watched):
            with _CACHE_LOCK:
                _CACHE[key] = (time.monotonic() + CACHE_SECONDS, watched,
                               json.dumps(result, ensure_ascii=False))
                _CACHE.move_to_end(key)
                while len(_CACHE) > MAX_CACHED_INSPECTIONS:
                    _CACHE.popitem(last=False)
        return result
    finally:
        with _CACHE_LOCK:
            _IN_FLIGHT.discard(key)
