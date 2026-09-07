"""Archive completed AR evidence before retiring its expired staging copy."""
from __future__ import annotations

from .ar_skill_identity import AR_SKILL_IDS

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from .ar_execution_contract import CONTRACT_VERSION
from .ar_retention_policy import workflow_retention_hold
from .ar_staging_archive import ARCHIVE_DIR, ArchiveError, build_archive, inventory, open_archive, remove_quarantine
from .audit_service import record_audit
from .models import AuditEvent, FileRecord, WorkflowAction, WorkflowSession
from .scheduler import acquire_claim_lock
from .settings import settings


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _load(db, workflow_id: str, *, locked: bool = False):
    db.rollback()
    if locked:
        acquire_claim_lock(db)
    workflow = db.scalar(select(WorkflowSession).where(WorkflowSession.id == workflow_id)
                         .options(selectinload(WorkflowSession.actions), selectinload(WorkflowSession.batch))
                         .execution_options(populate_existing=True))
    if workflow is None:
        raise ArchiveError("原核销任务不存在，不能归档或清理暂存。")
    return workflow, json.loads(workflow.context_json or "{}")


def archive_location(db, workflow, context: dict) -> tuple[Path, Path, dict]:
    from .workflow_service import WRITE_STAGING_DIR, _controlled_context_workspace, _workflow_storage_root

    workspace = _controlled_context_workspace(_workflow_storage_root(db, workflow), workflow)
    state = context.get("ar_execution") or {}
    staged = (state.get("steps") or {}).get("stage_reconciliation") or {}
    stage = Path(str(staged.get("staging_workspace") or ""))
    if (state.get("schema_version") != CONTRACT_VERSION or not stage.is_absolute()
            or stage.parent.resolve() != (workspace / WRITE_STAGING_DIR).resolve()
            or not stage.resolve().is_relative_to(workspace)
            or stage.resolve() != Path(str(context.get("published_workspace") or "")).resolve()
            or stage.is_symlink()):
        raise ArchiveError("暂存与本日固定执行、发布目录不一致，已保留原目录。")
    binding = {"workflow_id": workflow.id, "owner_id": workflow.owner_id,
               "department_id": workflow.department_id, "skill_hash": workflow.skill_hash,
               "date": workflow.reconciliation_date, "source": stage.relative_to(workspace).as_posix(),
               "execution_sha256": hashlib.sha256(_json({"execution": state,
                   "formal_ledgers": context.get("formal_ledgers"),
                   "final_result": context.get("final_result")}).encode()).hexdigest()}
    directory = workspace / ARCHIVE_DIR
    if directory.is_symlink() or not directory.resolve().is_relative_to(workspace):
        raise ArchiveError("暂存归档目录越界，已保留原目录。")
    return stage, directory, binding


def registered_archive(db, workflow, context: dict) -> tuple[dict, Path] | None:
    retention = context.get("ar_staging_retention") or {}
    if retention.get("state") not in {"verified", "purging", "purged"}:
        return None
    _, directory, binding = archive_location(db, workflow, context)
    reference = retention.get("archive") or {}
    if reference.get("binding") != binding:
        raise ArchiveError("暂存归档与原核销执行记录不一致，不能替代历史报告输入。")
    return reference, directory


def _hold(db, workflow, stage: Path) -> dict | None:
    hold = workflow_retention_hold(workflow)
    if hold:
        return hold
    # A future linked recovery must not lose its source just because the source
    # itself succeeded. Only bound references matter, never an age assumption.
    references = list(db.scalars(select(WorkflowSession).where(
        WorkflowSession.id != workflow.id,
        or_(WorkflowSession.context_json.contains(workflow.id, autoescape=True),
            WorkflowSession.context_json.contains(json.dumps(str(stage), ensure_ascii=False)[1:-1], autoescape=True)),
    ).options(selectinload(WorkflowSession.actions), selectinload(WorkflowSession.batch)).limit(501)))
    if len(references) > 500:
        return {"code": "reference_limit", "message": "暂存关联任务超过核查上限，保留原目录。"}
    if any(workflow_retention_hold(item) or item.state not in {"succeeded", "failed", "cancelled"}
           or any(action.state in {"queued", "running"} for action in item.actions)
           for item in references):
        return {"code": "unresolved_reference", "message": "仍有未完成或未核清的关联任务引用原执行，保留暂存。"}
    records = list(db.scalars(select(FileRecord).where(
        FileRecord.stored_path.startswith(str(stage), autoescape=True)).limit(501)))
    if len(records) > 500 or any(Path(item.stored_path).resolve().is_relative_to(stage.resolve()) for item in records):
        return {"code": "registered_staging_file", "message": "仍有平台登记文件直接存放在暂存内，未清理其下载来源。"}
    return None


def _save(db, workflow, context, retention: dict, code: str, message: str) -> None:
    previous = context.get("ar_staging_retention") or {}
    context["ar_staging_retention"] = {**retention, "reason_code": code, "reason": message}
    context["staging_retention_complete"] = retention.get("state") == "purged"
    workflow.context_json = _json(context)
    if previous.get("reason_code") != code or previous.get("state") != retention.get("state"):
        record_audit(db, actor_role="system", department_id=workflow.department_id,
                     action="workflow.ar_staging.retention", resource_type="workflow", resource_id=workflow.id,
                     details={"state": retention.get("state"), "reason_code": code, "reason": message})
    db.commit()


def _verify_publication(db, workflow, context: dict) -> None:
    from .ar_formal_ledger_service import read_formal_ledger_bundle
    from .ar_publication import published_report
    from .ar_staging_archive import _digest

    try:
        read_formal_ledger_bundle(db, workflow)
        token = workflow.reconciliation_date.replace("-", "")
        for name in (f"核销日清_{token}.xlsx", f"最终核销结果_{token}.json"):
            report = published_report(db, workflow, name)
            if _digest(report.path) != report.sha256:
                raise ArchiveError("正式报告实际文件与发布指纹不一致，未清理暂存。")
            if name.endswith(".json") and report.sha256 != (context.get("final_result") or {}).get("fingerprint"):
                raise ArchiveError("正式最终结果与原复核指纹不一致，未清理暂存。")
    except ArchiveError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ArchiveError("正式材料、辅助台账或报告的实际文件未通过发布回读，已保留暂存及归档供核查。") from exc


def _verify_archive_execution(reference: dict, directory: Path, context: dict, stage: Path) -> None:
    steps = context["ar_execution"]["steps"]
    original = steps["stage_reconciliation"]["manifest"]
    protected = original.get("protected_inputs")
    workbooks = steps["build_final_report"].get("files")
    if not isinstance(protected, dict) or len(protected) < 4 or not isinstance(workbooks, dict) or not workbooks:
        raise ArchiveError("原执行缺少完整保护清单或最终工作簿指纹，未清理暂存。")
    expected = {**protected, **workbooks}
    for ref in (context.get("final_result") or {}, steps["complete_reconciliation"]["formal_ledger_candidate"]):
        path = Path(str(ref.get("path") or "")).resolve()
        if not path.is_relative_to(stage.resolve()):
            raise ArchiveError("原最终结果或正式台账候选不属于固定暂存，未清理。")
        expected[path.relative_to(stage.resolve()).as_posix()] = ref.get("fingerprint")
    with open_archive(reference, directory) as (archive, manifest):
        if any((manifest["files"].get(name) or {}).get("sha256") != digest for name, digest in expected.items()):
            raise ArchiveError("暂存归档与原计划、首次日清、最终工作簿或复核结果指纹不一致，已保留原目录。")
        info = archive.getinfo("evidence/execution-manifest.json")
        if info.file_size > 8 * 1024**2 or json.loads(archive.read(info)) != original:
            raise ArchiveError("暂存归档内的执行清单与原任务登记不一致，未清理原目录。")


def _discard_unregistered_attempts(directory: Path, attempts: list[str]) -> None:
    from .ar_staging_archive import _regular

    _regular(directory, directory=True)
    for attempt in reversed(attempts):
        if not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt):
            raise ArchiveError("失效归档尝试标识无效，未删除任何未核清文件。")
        folder = directory / attempt
        if folder.exists():
            _regular(folder, directory=True)
            entries = list(folder.iterdir())
            path = folder / "evidence.zip"
            if any(item != path for item in entries):
                raise ArchiveError("失效归档目录包含未登记文件，已暂停清理与新建。")
            try:
                if path.exists():
                    _regular(path)
                    path.unlink()
                folder.rmdir()
            except OSError as exc:
                raise ArchiveError("上次未登记的归档文件仍被占用或无法清理，暂停新建归档，避免重复占用磁盘。") from exc


def maintain_staging(db, workflow_id: str) -> bool:
    """Only maintenance is retried. This function never queues a business action."""
    now = datetime.now(UTC)
    workflow, context = _load(db, workflow_id, locked=True)
    retention = context.get("ar_staging_retention") or {}
    if retention.get("state") == "purged":
        db.rollback()
        return False
    next_check = retention.get("next_check_at")
    if next_check and _utc(datetime.fromisoformat(next_check)) > now:
        db.rollback()
        return False
    stage, directory, binding = archive_location(db, workflow, context)
    hold = _hold(db, workflow, stage)
    if hold:
        _save(db, workflow, context, {**retention, "next_check_at": (now + timedelta(hours=1)).isoformat()},
              hold["code"], hold["message"])
        return True
    complete = [item.finished_at for item in workflow.actions
                if item.name == "ar_complete_reconciliation" and item.finished_at is not None]
    days = settings.ar_staging_retention_days
    if days <= 0 or not complete or max(map(_utc, complete)) + timedelta(days=days) > now:
        db.rollback()
        return False
    reference = retention.get("archive")
    attempt = str(retention.get("attempt") or "")
    maintenance_id = uuid.uuid4().hex
    if attempt and not re.fullmatch(r"[0-9a-f]{32}", attempt):
        raise ArchiveError("当前归档尝试标识无效，未清理或新建归档。")
    if retention.get("state") not in {"verified", "purging"}:
        from .ar_staging_archive import _regular

        discarded = list(retention.get("discarded_attempts") or [])
        if any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{32}", item) for item in discarded):
            raise ArchiveError("失效归档尝试标识无效，未开始清理或新建。")
        discarded = [item for item in discarded if (directory / item).exists()]
        if attempt and attempt not in discarded and (directory / attempt).exists():
            discarded.append(attempt)
        attempt = uuid.uuid4().hex
        directory.mkdir(exist_ok=True)
        _regular(directory, directory=True)
        # Create the attempt's parent while fenced, before allowing I/O. Once
        # retired, a late old builder cannot recreate it or publish a stray ZIP.
        attempt_dir = directory / attempt
        attempt_dir.mkdir()
        retention = {"state": "building", "attempt": attempt,
                     "maintenance_id": maintenance_id,
                     "discarded_attempts": discarded,
                     "next_check_at": (now + timedelta(hours=1)).isoformat()}
        _save(db, workflow, context, retention, "archiving", "暂存已到保留期限，正在建立并回读证据归档；原目录尚未删除。")
        try:
            # The committed new attempt fences an expired builder before its
            # unregistered scratch ZIP can be removed. It cannot register that
            # ZIP or rename staging. A busy Windows file defers the next build.
            _discard_unregistered_attempts(directory, discarded)
            workflow, context = _load(db, workflow_id, locked=True)
            if (context.get("ar_staging_retention") or {}).get("maintenance_id") != maintenance_id:
                db.rollback()
                return True
            context["ar_staging_retention"]["discarded_attempts"] = []
            workflow.context_json = _json(context)
            db.commit()
            reference, before = build_archive(stage, attempt_dir / "evidence.zip", binding)
            _verify_archive_execution(reference, directory, context, stage)
            workflow, context = _load(db, workflow_id, locked=True)
            current = context.get("ar_staging_retention") or {}
            current_stage, current_directory, current_binding = archive_location(db, workflow, context)
            if current.get("attempt") != attempt or current.get("maintenance_id") != maintenance_id:
                db.rollback()
                return True  # An expired attempt can finish only its own ZIP.
            if (current_binding != binding or current_stage != stage or current_directory != directory
                    or _hold(db, workflow, stage) or inventory(stage) != before):
                raise ArchiveError("归档期间任务、引用或暂存文件发生变化，已保留原目录。")
            retention = {**current, "state": "verified", "archive": reference,
                         "source_inventory": before, "next_check_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
            _save(db, workflow, context, retention, "archive_verified", "证据归档已逐文件回读，待清理过期暂存副本。")
        except Exception as exc:
            return _failed(db, workflow_id, attempt, exc, maintenance_id)
    else:
        retention = {**retention, "maintenance_id": maintenance_id,
                     "next_check_at": (now + timedelta(hours=1)).isoformat()}
        _save(db, workflow, context, retention, "archive_rechecking", "正在重新核查正式发布与归档，再继续清理隔离副本。")
    try:
        # Registered reports now read the archive. Hash it again outside the
        # claim lock before fencing the final directory rename.
        db.rollback()
        workflow, checked_context = _load(db, workflow_id)
        if archive_location(db, workflow, checked_context)[2] != binding:
            raise ArchiveError("清理前核销执行记录发生变化，已保留暂存及归档。")
        _verify_publication(db, workflow, checked_context)
        db.rollback()
        _verify_archive_execution(reference, directory, checked_context, stage)
        workflow, context = _load(db, workflow_id, locked=True)
        current = context.get("ar_staging_retention") or {}
        current_stage, current_directory, current_binding = archive_location(db, workflow, context)
        if (current.get("attempt") != attempt or current.get("maintenance_id") != maintenance_id
                or current.get("state") == "purged"):
            db.rollback()
            return True
        if (current.get("archive") != reference or reference.get("binding") != current_binding
                or current_stage != stage or current_directory != directory or _hold(db, workflow, stage)):
            raise ArchiveError("清理前任务、发布或关联引用已变化，保留暂存及归档。")
        quarantine = directory / f"{stage.name}.purging"
        if stage.exists():
            if quarantine.exists() or inventory(stage) != current.get("source_inventory"):
                raise ArchiveError("待清理暂存与归档时的目录不一致，未删除原目录。")
            os.rename(stage, quarantine)
        elif not quarantine.exists() and current.get("state") != "purging":
            raise ArchiveError("原暂存和清理隔离目录均缺失，不能宣称已完成清理。")
        retention = {**current, "state": "purging", "next_check_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
        _save(db, workflow, context, retention, "staging_purging", "证据归档已登记，正在清理隔离的过期暂存副本。")
        next_heartbeat = datetime.now(UTC)

        def heartbeat():
            nonlocal next_heartbeat
            at = datetime.now(UTC)
            if at < next_heartbeat:
                return
            active, active_context = _load(db, workflow_id, locked=True)
            active_retention = active_context.get("ar_staging_retention") or {}
            if (active_retention.get("maintenance_id") != maintenance_id
                    or active_retention.get("state") != "purging"
                    or _utc(datetime.fromisoformat(active_retention["next_check_at"])) <= at):
                raise ArchiveError("本次暂存维护租约已结束，停止后续清理，由当前维护记录继续核查。")
            active_retention["next_check_at"] = (at + timedelta(hours=1)).isoformat()
            active.context_json = _json(active_context)
            db.commit()
            next_heartbeat = at + timedelta(seconds=30)

        remove_quarantine(quarantine, directory, current.get("source_inventory") or {}, heartbeat)
        workflow, context = _load(db, workflow_id, locked=True)
        current = context.get("ar_staging_retention") or {}
        if current.get("attempt") == attempt and current.get("maintenance_id") == maintenance_id:
            retention = {key: value for key, value in current.items() if key not in {"source_inventory", "next_check_at"}}
            _save(db, workflow, context, {**retention, "state": "purged", "purged_at": datetime.now(UTC).isoformat()},
                  "staging_archived", "过期暂存副本已清理；正式材料、逐单证据及证据归档保留，归档不能用于重新核销或取数回放。")
        else:
            db.rollback()
        return True
    except Exception as exc:
        return _failed(db, workflow_id, attempt, exc, maintenance_id)


def _failed(db, workflow_id: str, attempt: str, exc: Exception, maintenance_id: str | None = None) -> bool:
    workflow, context = _load(db, workflow_id, locked=True)
    retention = context.get("ar_staging_retention") or {}
    if (str(retention.get("attempt") or "") == attempt and retention.get("state") != "purged"
            and (maintenance_id is None or retention.get("maintenance_id") == maintenance_id)):
        message = str(exc) if isinstance(exc, ArchiveError) else "暂存归档或隔离副本清理失败，未改变核销结果；保留现有证据，一小时后重新核查。"
        _save(db, workflow, context, {**retention, "next_check_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
              "archive_cleanup_failed", message)
    else:
        db.rollback()
    return True


def maintain_expired_staging(db) -> bool:
    if settings.ar_staging_retention_days <= 0:
        return False
    cutoff = datetime.now(UTC) - timedelta(days=settings.ar_staging_retention_days)
    completed = select(WorkflowAction.workflow_id).where(
        WorkflowAction.name == "ar_complete_reconciliation", WorkflowAction.state == "succeeded",
        WorkflowAction.finished_at <= cutoff)
    ids = list(db.scalars(select(WorkflowSession.id).where(
        WorkflowSession.skill_id.in_(AR_SKILL_IDS), WorkflowSession.state == "succeeded",
        WorkflowSession.id.in_(completed),
        ~WorkflowSession.context_json.contains('"staging_retention_complete": true', autoescape=True),
    ).order_by(WorkflowSession.updated_at, WorkflowSession.id).limit(100)))
    db.rollback()
    for workflow_id in ids:
        try:
            if maintain_staging(db, workflow_id):
                return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # A malformed historical entry must neither grant deletion nor
            # prevent the rest of the due candidates from being considered.
            db.rollback()
            try:
                workflow, context = _load(db, workflow_id)
                retention = context.get("ar_staging_retention") or {}
                _failed(db, workflow_id, str(retention.get("attempt") or ""), exc)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                db.rollback()
                # Keep an unreadable original context intact. A deduplicated
                # audit explains the hold without flooding the worker log.
                workflow = db.get(WorkflowSession, workflow_id)
                audit_action = "workflow.ar_staging.unreadable"
                previous = db.scalar(select(AuditEvent.id).where(
                    AuditEvent.action == audit_action, AuditEvent.resource_id == workflow_id).limit(1))
                if workflow is not None and previous is None:
                    record_audit(db, actor_role="system", department_id=workflow.department_id,
                                 action=audit_action, resource_type="workflow", resource_id=workflow_id,
                                 details={"reason_code": "retention_context_unreadable",
                                          "reason": "原任务或维护记录无法解析，保留原文及暂存，未开始删除。"})
                db.commit()
    return False
