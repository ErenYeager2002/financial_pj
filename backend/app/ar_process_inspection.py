"""Verify task-owned process facts and observe identity without changing processes."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .ar_process_evidence import SCHEMA_VERSION
from .ar_process_identity import observe_identity
from .resource_policy import workflow_root

MAX_RECORDS = 128
MAX_FACT_BYTES = 16 * 1024
HASH = re.compile(r"[0-9a-f]{64}")
RECORD = re.compile(r"[0-9a-f]{32}")
BINDING_FIELDS = (
    "schema_version", "record_id", "workflow_id", "action_id", "action_name", "attempt",
    "worker_id", "reconciliation_date", "skill_hash", "material_set_id", "material_version",
    "plan_fingerprint", "host", "worker_pid", "script", "script_sha256", "arguments_sha256",
)


class ProcessEvidenceError(ValueError):
    """A fixed, non-sensitive validation reason."""


def _read_fact(path: Path, root: Path, fingerprint: str) -> dict:
    if (not isinstance(fingerprint, str) or not HASH.fullmatch(fingerprint)
            or path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file()):
        raise ProcessEvidenceError("进程证据文件或登记指纹缺失。")
    with path.open("rb") as handle:
        raw = handle.read(MAX_FACT_BYTES + 1)
    if len(raw) > MAX_FACT_BYTES or hashlib.sha256(raw).hexdigest() != fingerprint:
        raise ProcessEvidenceError("进程证据超过大小限制或与登记指纹不一致。")
    fact = json.loads(raw)
    if not isinstance(fact, dict):
        raise ProcessEvidenceError("进程证据内容格式无效。")
    return fact


def inspect_process_evidence(workflow, action, failure: dict) -> dict:
    """Only a complete set of registered facts can substantiate a stop claim."""
    summary = {"state": "not_recorded", "message": "未记录可核验的脚本进程证据。",
               "verified": False, "total": 0, "exited": 0, "unconfirmed": 0}
    liveness = {}
    observed = []
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    journal = root / "execution-processes" / action.id
    try:
        if action.workflow_id != workflow.id or failure.get("action_id") != action.id:
            raise ProcessEvidenceError("进程证据与当前失败动作不一致。")
        if journal.is_symlink() or not journal.resolve().is_relative_to(root):
            raise ProcessEvidenceError("进程证据目录不属于当前任务。")
        found = set()
        if journal.exists():
            for path in journal.iterdir():
                if path.is_symlink() or not path.is_dir() or not RECORD.fullmatch(path.name):
                    raise ProcessEvidenceError("进程证据目录存在非预期内容。")
                found.add(path.name)
                if len(found) > MAX_RECORDS:
                    raise ProcessEvidenceError("进程证据数量超过核查上限，未忽略其余记录。")
        refs = failure.get("process_records")
        if failure.get("process_evidence_version") != SCHEMA_VERSION:
            summary.update(state="unregistered" if found else "not_recorded", total=len(found),
                           message="原动作未登记完整的进程证据引用；现存文件不能单独证明原执行已停止。")
        elif not isinstance(refs, list) or len(refs) > MAX_RECORDS:
            raise ProcessEvidenceError("进程证据引用缺失或超过核查上限。")
        else:
            ids = [item.get("record_id") if isinstance(item, dict) else None for item in refs]
            if (any(not isinstance(value, str) or not RECORD.fullmatch(value) for value in ids)
                    or len(ids) != len(set(ids)) or set(ids) != found):
                raise ProcessEvidenceError("登记的脚本调用与现存进程证据不完全对应。")
            summary["total"] = len(refs)
            context = json.loads(workflow.context_json or "{}")
            execution = context.get("ar_execution") or {}
            for ref in refs:
                directory = journal / ref["record_id"]
                prepared = _read_fact(directory / "prepared.json", root, ref.get("prepared_sha256"))
                expected = {
                    "schema_version": SCHEMA_VERSION, "record_id": ref["record_id"],
                    "workflow_id": workflow.id, "action_id": action.id, "action_name": action.name,
                    "attempt": action.attempt_count, "reconciliation_date": workflow.reconciliation_date,
                    "skill_hash": workflow.skill_hash, "script": ref.get("script"),
                    "material_set_id": execution.get("material_set_id"),
                    "material_version": execution.get("material_version"),
                    "plan_fingerprint": context.get("plan_fingerprint"),
                }
                if any(prepared.get(key) != value for key, value in expected.items()):
                    raise ProcessEvidenceError("进程证据的任务、动作、输入版本或脚本绑定不一致。")
                if not re.fullmatch(r"[a-z_]+\.py", str(prepared.get("script") or "")):
                    raise ProcessEvidenceError("进程证据脚本名称无效。")
                if not all(isinstance(prepared.get(key), str) and HASH.fullmatch(prepared[key])
                           for key in ("script_sha256", "arguments_sha256")):
                    raise ProcessEvidenceError("进程证据缺少脚本或参数指纹。")
                observed.append(ref["prepared_sha256"])
                if not ref.get("started_sha256"):
                    summary["unconfirmed"] += 1
                    continue
                started = _read_fact(directory / "started.json", root, ref["started_sha256"])
                if any(started.get(key) != prepared.get(key) for key in BINDING_FIELDS):
                    raise ProcessEvidenceError("脚本启动事实与原调用绑定不一致。")
                identity = started.get("identity")
                if isinstance(identity, dict) and identity.get("available") is True and identity.get("pid") != started.get("pid"):
                    raise ProcessEvidenceError("进程身份与脚本启动 PID 不一致。")
                live = observe_identity(identity)
                liveness[live] = liveness.get(live, 0) + 1
                observed.append(ref["started_sha256"])
                if not ref.get("exit_sha256"):
                    summary["unconfirmed"] += 1
                    continue
                exited = _read_fact(directory / "exited.json", root, ref["exit_sha256"])
                if any(fact.get(key) != prepared.get(key) for key in BINDING_FIELDS for fact in (started, exited)):
                    raise ProcessEvidenceError("同一脚本的启动与退出事实绑定不一致。")
                if (type(started.get("pid")) is not int or started["pid"] <= 0
                        or exited.get("pid") != started["pid"] or type(exited.get("returncode")) is not int
                        or exited.get("direct_process_exit_confirmed") is not True):
                    raise ProcessEvidenceError("脚本退出事实缺少一致的进程标识或退出码。")
                if live == "running":
                    raise ProcessEvidenceError("退出记录与当前仍存活的原进程身份冲突。")
                observed.append(ref["exit_sha256"])
                summary["exited"] += 1
                if exited.get("communication_completed") is not True:
                    summary["unconfirmed"] += 1
            if summary["unconfirmed"]:
                summary.update(state="unconfirmed", message=(
                    f"已核验 {summary['exited']} 个直接脚本进程退出；{summary['unconfirmed']} 次调用缺少完整启动/退出记录或通信中断。"
                    "外部应用及阶段结果仍需核查，不能据此恢复。"))
            elif not refs:
                summary.update(state="not_started", verified=failure.get("process_exit_confirmed") is True,
                               message="原 Worker 记录本阶段未启动脚本，未发现额外进程记录；尚不代表业务阶段已完成。")
            else:
                summary.update(state="verified", verified=True,
                               message=f"已按登记指纹核验 {len(refs)} 次脚本调用的启动和退出事实；财务结果仍须单独回读与复核。")
    except ProcessEvidenceError as exc:
        summary.update(state="invalid", verified=False, message=f"{exc} 禁止据此恢复。")
    except (OSError, ValueError, TypeError, KeyError):
        # Do not expose raw filesystem paths, host/PID metadata or file content.
        summary.update(state="invalid", verified=False,
                       message="进程证据缺失、内容无效或与登记指纹及任务绑定不一致；禁止据此恢复。")
    if liveness:
        labels = {"running": "原进程当前仍存活", "not_running": "当前查询未发现原进程存活",
                  "exited_unreaped": "原进程已退出但尚未回收", "identity_changed": "PID 当前身份与原记录不同",
                  "different_scope": "无法确认与原执行处于相同宿主和进程空间",
                  "not_recorded": "未记录可查询的进程身份", "unavailable": "进程查询不可用或权限不足"}
        summary["message"] += " 当前存活调查：" + "；".join(
            f"{labels[key]} {value} 次" for key, value in sorted(liveness.items())
        ) + "。此调查不证明外部应用已停止或业务写入成功。"
    summary["liveness"] = liveness
    summary["fingerprint"] = hashlib.sha256(json.dumps(
        {"summary": summary, "observed": observed}, ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    return summary
