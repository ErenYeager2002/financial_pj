from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import FetchedBundle, FetchedBundleFile, WorkflowAction, WorkflowSession
from .resource_policy import SAFE_STORAGE_COMPONENT
from .settings import settings
from .storage import sha256_file

FETCH_BUNDLE_DATASETS = frozenset({"payments", "orders", "writeoffs", "order_details", "summary"})


class FetchedBundleError(ValueError):
    """A safe lifecycle or integrity error that contains no business-row data."""


@dataclass(frozen=True)
class FetchExportFile:
    dataset: Literal["payments", "orders", "writeoffs", "order_details", "summary"]
    reconciliation_date: str
    relative_name: str


@dataclass(frozen=True)
class FetchManifest:
    manifest_version: str
    files: tuple[FetchExportFile, ...]


class FetchSource(Protocol):
    source_type: Literal["live", "replay"]

    def export(self, dates: list[str], target: Path) -> FetchManifest: ...


@dataclass(frozen=True)
class FetchedBundleResult:
    bundle_id: str
    source_type: Literal["live", "replay"]
    state: str
    dates: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedReplayBundle:
    bundle: FetchedBundle
    deprecated_reference: bool


@dataclass(frozen=True)
class _ValidatedFile:
    dataset: str
    reconciliation_date: str
    relative_name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class LiveZhiyunFetchAdapter:
    exporter: Callable[[list[str], Path], FetchManifest]
    source_type: Literal["live"] = "live"

    def export(self, dates: list[str], target: Path) -> FetchManifest:
        return self.exporter(dates, target)


def _normalized_dates(values: list[str]) -> list[str]:
    dates: list[str] = []
    for value in values:
        text = str(value or "").strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise FetchedBundleError("取数包包含无效核销日期。") from exc
        canonical = parsed.isoformat()
        if canonical not in dates:
            dates.append(canonical)
    dates.sort()
    if not dates:
        raise FetchedBundleError("取数包至少需要一个核销日期。")
    return dates


def _safe_owner_component(owner_id: str) -> str:
    if not SAFE_STORAGE_COMPONENT.fullmatch(owner_id):
        raise FetchedBundleError("取数包所有者标识无效。")
    return owner_id


def _bundle_storage_root() -> Path:
    return (settings.data_dir / "fetched-bundles").resolve()


def _owner_storage_root(owner_id: str) -> Path:
    root = _bundle_storage_root()
    owner_root = (root / _safe_owner_component(owner_id)).resolve()
    if not owner_root.is_relative_to(root):
        raise FetchedBundleError("取数包存储范围无效。")
    return owner_root


def _bundle_storage_path(bundle: FetchedBundle) -> Path:
    expected_key = f"{bundle.owner_id}/{bundle.id}"
    if bundle.storage_key != expected_key or not SAFE_STORAGE_COMPONENT.fullmatch(bundle.id):
        raise FetchedBundleError("取数包存储标识无效。")
    root = _bundle_storage_root()
    path = (root / bundle.owner_id / bundle.id).resolve()
    if not path.is_relative_to(root):
        raise FetchedBundleError("取数包存储范围无效。")
    return path


def _validated_manifest_files(
    manifest: FetchManifest,
    dates: list[str],
    target: Path,
) -> list[_ValidatedFile]:
    version = str(manifest.manifest_version or "").strip()
    if not version or len(version) > 64:
        raise FetchedBundleError("取数包清单版本无效。")
    expected = {(item, dataset) for item in dates for dataset in FETCH_BUNDLE_DATASETS}
    declared: dict[tuple[str, str], FetchExportFile] = {}
    declared_names: set[str] = set()
    for item in manifest.files:
        key = (item.reconciliation_date, item.dataset)
        if item.reconciliation_date not in dates or item.dataset not in FETCH_BUNDLE_DATASETS:
            raise FetchedBundleError("取数包清单包含未允许的日期或数据集。")
        if key in declared:
            raise FetchedBundleError("同一日期的数据集在取数包中重复出现。")
        relative = Path(item.relative_name)
        if (
            relative.is_absolute()
            or relative.name != item.relative_name
            or item.relative_name in {"", ".", "..", "manifest.json"}
        ):
            raise FetchedBundleError("取数包成员路径无效。")
        if item.relative_name in declared_names:
            raise FetchedBundleError("取数包成员文件名重复。")
        declared[key] = item
        declared_names.add(item.relative_name)
    if set(declared) != expected:
        raise FetchedBundleError("取数包数据集不完整。")

    actual_names = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    unknown_names = actual_names - declared_names
    if unknown_names:
        raise FetchedBundleError("取数包包含未知文件。")
    if declared_names - actual_names:
        raise FetchedBundleError("取数包缺少清单成员。")

    validated: list[_ValidatedFile] = []
    target_root = target.resolve()
    for key in sorted(declared):
        item = declared[key]
        path = target / item.relative_name
        if path.is_symlink() or not path.is_file():
            raise FetchedBundleError("取数包成员不是普通文件。")
        resolved = path.resolve()
        if not resolved.is_relative_to(target_root):
            raise FetchedBundleError("取数包成员超出受控目录。")
        validated.append(
            _ValidatedFile(
                dataset=item.dataset,
                reconciliation_date=item.reconciliation_date,
                relative_name=item.relative_name,
                sha256=sha256_file(resolved),
                size_bytes=resolved.stat().st_size,
            )
        )
    _validate_export_summaries(
        target,
        manifest_version=version,
        dates=dates,
        files=validated,
    )
    return validated


def _validate_export_summaries(
    target: Path,
    *,
    manifest_version: str,
    dates: list[str],
    files: list[_ValidatedFile],
) -> None:
    export_schema_version = manifest_version
    base_version, separator, revision = manifest_version.rpartition("-s")
    if (
        separator
        and len(revision) == 12
        and all(character in "0123456789abcdef" for character in revision)
    ):
        export_schema_version = base_version
    by_date = {
        reconciliation_date: [
            item
            for item in files
            if item.reconciliation_date == reconciliation_date and item.dataset != "summary"
        ]
        for reconciliation_date in dates
    }
    summaries = {item.reconciliation_date: item for item in files if item.dataset == "summary"}
    for reconciliation_date in dates:
        summary_file = summaries[reconciliation_date]
        try:
            summary = json.loads((target / summary_file.relative_name).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FetchedBundleError("取数摘要格式无效。") from exc
        if not isinstance(summary, dict):
            raise FetchedBundleError("取数摘要格式无效。")
        if (
            summary.get("day") != reconciliation_date
            or summary.get("export_schema_version") != export_schema_version
            or summary.get("read_only") is not True
        ):
            raise FetchedBundleError("取数摘要的日期、版本或只读标记无效。")
        hashes = summary.get("file_sha256")
        expected_hashes = {item.relative_name: item.sha256 for item in by_date[reconciliation_date]}
        if not isinstance(hashes, dict) or set(hashes) != set(expected_hashes):
            raise FetchedBundleError("取数摘要的文件哈希清单不完整。")
        if any(
            not isinstance(hashes[name], str) or hashes[name].casefold() != expected.casefold()
            for name, expected in expected_hashes.items()
        ):
            raise FetchedBundleError("取数摘要的文件哈希不一致。")


def _write_manifest(
    target: Path,
    *,
    bundle_id: str,
    source_type: str,
    manifest_version: str,
    dates: list[str],
    files: list[_ValidatedFile],
) -> None:
    payload = {
        "bundle_id": bundle_id,
        "source_type": source_type,
        "manifest_version": manifest_version,
        "dates": dates,
        "files": [
            {
                "dataset": item.dataset,
                "reconciliation_date": item.reconciliation_date,
                "relative_name": item.relative_name,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in files
        ],
    }
    (target / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _make_read_only(target: Path) -> None:
    for path in target.iterdir():
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD)
    if os.name != "nt":
        target.chmod(stat.S_IREAD | stat.S_IEXEC)


def _remove_tree(target: Path) -> None:
    if target.is_symlink():
        target.unlink()
        return
    if not target.exists():
        return
    target.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    for path in target.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)
    shutil.rmtree(target)


def _file_signature(files: list[_ValidatedFile]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            item.reconciliation_date,
            item.dataset,
            item.relative_name,
            item.sha256,
            item.size_bytes,
        )
        for item in files
    )


def _stored_file_signature(
    files: list[FetchedBundleFile],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                item.reconciliation_date,
                item.dataset,
                item.relative_name,
                item.sha256,
                item.size_bytes,
            )
            for item in files
        )
    )


def _result(bundle: FetchedBundle) -> FetchedBundleResult:
    return FetchedBundleResult(
        bundle_id=bundle.id,
        source_type=bundle.source_type,  # type: ignore[arg-type]
        state=bundle.state,
        dates=tuple(json.loads(bundle.dates_json)),
    )


def materialize_bundle(
    db: Session,
    *,
    workflow: WorkflowSession,
    source: FetchSource,
    dates: list[str],
) -> FetchedBundleResult:
    normalized_dates = _normalized_dates(dates)
    if source.source_type not in {"live", "replay"}:
        raise FetchedBundleError("取数来源类型无效。")
    owner_root = _owner_storage_root(workflow.owner_id)
    owner_root.mkdir(parents=True, exist_ok=True)
    bundle_id = str(uuid.uuid4())
    temporary = owner_root / f".{bundle_id}.tmp"
    final = owner_root / bundle_id
    published = False
    now = datetime.now(UTC)
    retention_days = max(0, int(getattr(settings, "fetch_bundle_retention_days", 0)))
    dates_json = json.dumps(normalized_dates, ensure_ascii=False, separators=(",", ":"))
    bundle = FetchedBundle(
        id=bundle_id,
        owner_id=workflow.owner_id,
        department_id=workflow.department_id,
        skill_id=workflow.skill_id,
        source_workflow_id=workflow.id,
        source_batch_id=workflow.batch_id,
        source_type=source.source_type,
        manifest_version=f"creating-{bundle_id[:12]}",
        state="creating",
        date_from=normalized_dates[0],
        date_to=normalized_dates[-1],
        dates_json=dates_json,
        storage_key=f"{workflow.owner_id}/{bundle_id}",
        raw_available=False,
        preview_available=False,
        replayable=False,
        retention_until=now + timedelta(days=retention_days),
        created_at=now,
        last_error="",
    )
    discard_bundle_after_cleanup = False
    try:
        # Make every raw-data directory derivable from a durable lifecycle row,
        # including a process exit while the source adapter is still exporting.
        db.add(bundle)
        db.flush([bundle])
        db.commit()
        temporary.mkdir(exist_ok=False)
        manifest = source.export(normalized_dates, temporary)
        files = _validated_manifest_files(manifest, normalized_dates, temporary)
        existing = db.scalar(
            select(FetchedBundle).where(
                FetchedBundle.id != bundle.id,
                FetchedBundle.source_workflow_id == workflow.id,
                FetchedBundle.manifest_version == manifest.manifest_version,
                FetchedBundle.dates_json == dates_json,
            )
        )
        if existing is not None:
            if existing.source_type != source.source_type or _stored_file_signature(
                existing.files
            ) != _file_signature(files):
                discard_bundle_after_cleanup = True
                raise FetchedBundleError("重复取数请求的文件内容与现有取数包不一致。")
            _validated_bundle_members(existing, normalized_dates)
            discard_bundle_after_cleanup = True
            workflow.fetched_bundle_id = existing.id
            db.commit()
            return _result(existing)
        _write_manifest(
            temporary,
            bundle_id=bundle_id,
            source_type=source.source_type,
            manifest_version=manifest.manifest_version,
            dates=normalized_dates,
            files=files,
        )
        bundle.manifest_version = manifest.manifest_version
        bundle.files = [
            FetchedBundleFile(
                id=str(uuid.uuid4()),
                reconciliation_date=item.reconciliation_date,
                dataset=item.dataset,
                relative_name=item.relative_name,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
            )
            for item in files
        ]
        db.flush([bundle])
        db.commit()
        _make_read_only(temporary)
        os.replace(temporary, final)
        published = True
        bundle.state = "ready_for_review"
        bundle.raw_available = True
        bundle.replayable = retention_days > 0
        workflow.fetched_bundle_id = bundle.id
        db.flush([workflow])
        db.commit()
        return _result(bundle)
    except Exception:
        if published:
            _remove_tree(final)
        db.rollback()
        failed_bundle = db.get(FetchedBundle, bundle_id)
        if failed_bundle is not None and failed_bundle.state == "creating":
            failed_bundle.state = "invalid"
            failed_bundle.raw_available = False
            failed_bundle.replayable = False
            failed_bundle.retention_until = datetime.now(UTC)
            failed_bundle.last_error = "取数包发布失败，原始文件不可用。"
            db.commit()
        raise
    finally:
        temporary_cleanup_failed = False
        try:
            _remove_tree(temporary)
        except Exception:
            temporary_cleanup_failed = True
            db.rollback()
            failed_bundle = db.get(FetchedBundle, bundle_id)
            if failed_bundle is not None:
                failed_bundle.state = "invalid"
                failed_bundle.raw_available = True
                failed_bundle.replayable = False
                failed_bundle.retention_until = datetime.now(UTC)
                failed_bundle.last_error = "取数包临时文件清理失败，平台将自动重试。"
                db.commit()
        if discard_bundle_after_cleanup and not temporary_cleanup_failed:
            discarded_bundle = db.get(FetchedBundle, bundle_id)
            if discarded_bundle is not None:
                db.delete(discarded_bundle)
                db.commit()
        if owner_root.exists() and not any(owner_root.iterdir()):
            owner_root.rmdir()


def _owned_bundle(
    db: Session,
    bundle_id: str,
    owner_id: str,
    *,
    for_update: bool = False,
) -> FetchedBundle:
    statement = select(FetchedBundle).where(
        FetchedBundle.id == str(bundle_id or "").strip(),
        FetchedBundle.owner_id == owner_id,
    )
    if for_update:
        statement = statement.with_for_update()
    bundle = db.scalar(statement)
    if bundle is None:
        raise FetchedBundleError("取数包不存在。")
    return bundle


def _validated_bundle_members(
    bundle: FetchedBundle,
    dates: list[str],
) -> list[FetchedBundleFile]:
    root = _bundle_storage_path(bundle)
    if not root.is_dir() or root.is_symlink():
        raise FetchedBundleError("取数包原始文件不存在。")
    requested = set(_normalized_dates(dates))
    available = set(json.loads(bundle.dates_json))
    if not requested <= available:
        raise FetchedBundleError("取数包不包含所选核销日期。")
    all_members = list(bundle.files)
    selected = [item for item in all_members if item.reconciliation_date in requested]
    expected = {(item, dataset) for item in requested for dataset in FETCH_BUNDLE_DATASETS}
    if {(item.reconciliation_date, item.dataset) for item in selected} != expected:
        raise FetchedBundleError("取数包数据集不完整。")
    expected_names = {item.relative_name for item in all_members} | {"manifest.json"}
    actual_names = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_names != expected_names:
        raise FetchedBundleError("取数包目录包含未知文件或缺少已登记文件。")
    for item in all_members:
        path = root / item.relative_name
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
        ):
            raise FetchedBundleError("取数包成员无效。")
        if path.stat().st_size != item.size_bytes or sha256_file(path) != item.sha256:
            raise FetchedBundleError("取数包成员哈希不一致。")
    _validate_published_manifest(bundle, root, all_members)
    return selected


def _validate_published_manifest(
    bundle: FetchedBundle,
    root: Path,
    members: list[FetchedBundleFile],
) -> None:
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FetchedBundleError("取数包发布清单不存在。")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FetchedBundleError("取数包发布清单格式无效。") from exc
    expected_files = [
        {
            "dataset": item.dataset,
            "reconciliation_date": item.reconciliation_date,
            "relative_name": item.relative_name,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in sorted(
            members,
            key=lambda value: (value.reconciliation_date, value.dataset),
        )
    ]
    expected = {
        "bundle_id": bundle.id,
        "source_type": bundle.source_type,
        "manifest_version": bundle.manifest_version,
        "dates": json.loads(bundle.dates_json),
        "files": expected_files,
    }
    if manifest != expected:
        raise FetchedBundleError("取数包发布清单与数据库登记不一致。")


def confirm_bundle(
    db: Session,
    *,
    bundle_id: str,
    actor: object,
) -> FetchedBundle:
    owner_id = str(getattr(actor, "user_id", "") or "")
    bundle = _owned_bundle(db, bundle_id, owner_id, for_update=True)
    if bundle.state == "confirmed":
        return bundle
    if bundle.state != "ready_for_review" or not bundle.raw_available:
        raise FetchedBundleError("取数包当前不能确认。")
    bundle.state = "confirmed"
    bundle.confirmed_at = datetime.now(UTC)
    db.flush()
    return bundle


def assert_bundle_consumable(
    db: Session,
    *,
    bundle_id: str,
    owner_id: str,
    dates: list[str],
) -> FetchedBundle:
    bundle = _owned_bundle(db, bundle_id, owner_id)
    if bundle.state not in {"confirmed", "consumed"} or not bundle.raw_available:
        raise FetchedBundleError("取数包当前不能用于核销计划。")
    _validated_bundle_members(bundle, dates)
    return bundle


def assert_bundle_reviewable(
    db: Session,
    *,
    bundle_id: str,
    owner_id: str,
    dates: list[str],
) -> FetchedBundle:
    bundle = _owned_bundle(db, bundle_id, owner_id)
    if (
        bundle.state not in {"ready_for_review", "confirmed", "consumed"}
        or not bundle.raw_available
    ):
        raise FetchedBundleError("取数包当前不能用于建立预览。")
    _validated_bundle_members(bundle, dates)
    return bundle


def resolve_replay_bundle(
    db: Session,
    *,
    owner_id: str,
    skill_id: str,
    dates: list[str],
    bundle_id: str = "",
    source_workflow_id: str = "",
) -> ResolvedReplayBundle:
    current_time = datetime.now(UTC)
    direct_id = str(bundle_id or "").strip()
    legacy_id = str(source_workflow_id or "").strip()
    if direct_id and legacy_id:
        raise FetchedBundleError("取数包 ID 与旧任务 ID 不能同时提供。")
    if not direct_id and not legacy_id:
        raise FetchedBundleError("取数包 ID 不能为空。")
    deprecated = bool(legacy_id)
    if direct_id:
        bundle = db.scalar(
            select(FetchedBundle)
            .where(
                FetchedBundle.id == direct_id,
                FetchedBundle.owner_id == owner_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if bundle is None:
            raise FetchedBundleError("取数包不存在。")
        if bundle.skill_id != skill_id:
            raise FetchedBundleError("取数包不存在。")
    else:
        source = db.scalar(
            select(WorkflowSession).where(
                WorkflowSession.id == legacy_id,
                WorkflowSession.owner_id == owner_id,
                WorkflowSession.skill_id == skill_id,
            )
        )
        if source is None:
            raise FetchedBundleError("取数包不存在。")
        candidates = list(
            db.scalars(
                select(FetchedBundle)
                .where(
                    FetchedBundle.owner_id == owner_id,
                    FetchedBundle.skill_id == skill_id,
                    FetchedBundle.raw_available.is_(True),
                    FetchedBundle.replayable.is_(True),
                    FetchedBundle.state.in_(("confirmed", "consumed")),
                    or_(
                        FetchedBundle.retention_until.is_(None),
                        FetchedBundle.retention_until > current_time,
                    ),
                    or_(
                        FetchedBundle.source_workflow_id == legacy_id,
                        FetchedBundle.id == source.fetched_bundle_id,
                    ),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        unique = {item.id: item for item in candidates}
        if not unique:
            raise FetchedBundleError("旧任务没有可回放的取数包。")
        if len(unique) != 1:
            raise FetchedBundleError("旧任务对应多个取数包，请改用明确的取数包 ID。")
        bundle = next(iter(unique.values()))
    if not is_bundle_replayable(bundle, now=current_time):
        raise FetchedBundleError("取数包当前不可回放。")
    assert_bundle_consumable(
        db,
        bundle_id=bundle.id,
        owner_id=owner_id,
        dates=dates,
    )
    return ResolvedReplayBundle(bundle=bundle, deprecated_reference=deprecated)


def _assert_staged_members(
    target: Path,
    members: list[FetchedBundleFile],
) -> None:
    _assert_member_copy(
        target,
        members,
        missing_message="日期工作区的取数目录无效。",
        members_message="日期工作区的取数文件与取数包不一致。",
        hash_message="日期工作区的取数文件哈希不一致。",
    )


def _assert_member_copy(
    target: Path,
    members: list[FetchedBundleFile],
    *,
    missing_message: str,
    members_message: str,
    hash_message: str,
) -> None:
    if not target.is_dir() or target.is_symlink():
        raise FetchedBundleError(missing_message)
    expected_names = {item.relative_name for item in members}
    actual_names = {path.name for path in target.iterdir() if path.is_file() or path.is_symlink()}
    if actual_names != expected_names:
        raise FetchedBundleError(members_message)
    for item in members:
        path = target / item.relative_name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != item.size_bytes
            or sha256_file(path) != item.sha256
        ):
            raise FetchedBundleError(hash_message)


def _stage_validated_bundle_files(
    bundle: FetchedBundle,
    dates: list[str],
    target: Path,
) -> Path:
    members = _validated_bundle_members(bundle, dates)
    destination = Path(target).resolve()
    if destination.exists():
        _assert_staged_members(destination, members)
        return destination
    parent = destination.parent.resolve()
    if parent.is_symlink() or not parent.is_dir():
        raise FetchedBundleError("日期工作区的取数目录不在有效工作区中。")
    temporary = parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    source_root = _bundle_storage_path(bundle)
    try:
        temporary.mkdir(exist_ok=False)
        for item in members:
            source = source_root / item.relative_name
            staged = temporary / item.relative_name
            shutil.copyfile(source, staged)
        _assert_staged_members(temporary, members)
        os.replace(temporary, destination)
        return destination
    finally:
        _remove_tree(temporary)


def stage_bundle_files(
    db: Session,
    *,
    bundle_id: str,
    owner_id: str,
    dates: list[str],
    target: Path,
) -> Path:
    """Atomically stage confirmed bundle members for a reconciliation plan."""
    bundle = assert_bundle_consumable(
        db,
        bundle_id=bundle_id,
        owner_id=owner_id,
        dates=dates,
    )
    return _stage_validated_bundle_files(bundle, dates, target)


def stage_bundle_preview_files(
    db: Session,
    *,
    bundle_id: str,
    owner_id: str,
    dates: list[str],
    target: Path,
) -> Path:
    """Atomically stage a complete reviewable bundle mirror for preview recovery."""
    bundle = assert_bundle_reviewable(
        db,
        bundle_id=bundle_id,
        owner_id=owner_id,
        dates=dates,
    )
    return _stage_validated_bundle_files(bundle, dates, target)


def assert_bundle_preview_mirror(
    db: Session,
    *,
    bundle_id: str,
    owner_id: str,
    dates: list[str],
    mirror: Path,
) -> FetchedBundle:
    bundle = assert_bundle_reviewable(
        db,
        bundle_id=bundle_id,
        owner_id=owner_id,
        dates=dates,
    )
    members = _validated_bundle_members(bundle, dates)
    _assert_member_copy(
        mirror.resolve(),
        members,
        missing_message="取数预览目录不存在。",
        members_message="取数预览目录与已发布取数包不一致。",
        hash_message="取数预览文件与已发布取数包哈希不一致。",
    )
    return bundle


def finalize_bundle(db: Session, *, bundle_id: str, outcome: str) -> None:
    bundle = db.get(FetchedBundle, bundle_id)
    if bundle is None:
        raise FetchedBundleError("取数包不存在。")
    now = datetime.now(UTC)
    if outcome == "succeeded":
        if bundle.state == "consumed":
            bundle.replayable = bool(
                bundle.raw_available
                and (bundle.retention_until is None or _utc(bundle.retention_until) > _utc(now))
            )
            bundle.last_error = ""
            db.flush()
            return
        if bundle.state != "confirmed":
            raise FetchedBundleError("取数包尚未确认，不能完成消费。")
        bundle.state = "consumed"
        bundle.consumed_at = bundle.consumed_at or now
        bundle.replayable = bool(
            bundle.raw_available
            and (bundle.retention_until is None or _utc(bundle.retention_until) > _utc(now))
        )
        bundle.last_error = ""
    elif outcome in {"failed", "cancelled"}:
        if bundle.state == "invalid":
            return
        bundle.state = "invalid"
        bundle.replayable = False
        bundle.retention_until = now
        bundle.last_error = "任务未完成，取数包已停止消费。"
    else:
        raise FetchedBundleError("取数包完成结果无效。")
    db.flush()


def suspend_bundle_for_retry(db: Session, *, bundle_id: str) -> None:
    """Keep a verified failed-date bundle available only to its explicit retry path."""
    bundle = db.get(FetchedBundle, bundle_id)
    if bundle is None:
        raise FetchedBundleError("取数包不存在。")
    if (
        bundle.state not in {"ready_for_review", "confirmed", "consumed"}
        or not bundle.raw_available
    ):
        raise FetchedBundleError("取数包当前不能保留给失败日期重试。")
    now = datetime.now(UTC)
    retry_retention_days = max(
        1,
        int(getattr(settings, "fetch_bundle_retention_days", 0)),
    )
    retry_until = now + timedelta(days=retry_retention_days)
    if bundle.retention_until is None or _utc(bundle.retention_until) < retry_until:
        bundle.retention_until = retry_until
    bundle.replayable = False
    bundle.last_error = "任务未完成，取数包仅保留给原任务重试。"
    db.flush()


def _bundle_has_active_reference(db: Session, bundle_id: str) -> bool:
    active_workflow = db.scalar(
        select(WorkflowSession.id)
        .where(
            WorkflowSession.fetched_bundle_id == bundle_id,
            WorkflowSession.state.not_in(("succeeded", "failed", "cancelled")),
        )
        .limit(1)
    )
    if active_workflow is not None:
        return True
    active_source_workflow = db.scalar(
        select(WorkflowSession.id)
        .where(
            WorkflowSession.id
            == select(FetchedBundle.source_workflow_id)
            .where(FetchedBundle.id == bundle_id)
            .scalar_subquery(),
            WorkflowSession.state.not_in(("succeeded", "failed", "cancelled")),
        )
        .limit(1)
    )
    if active_source_workflow is not None:
        return True
    active_action = db.scalar(
        select(WorkflowAction.id)
        .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
        .where(
            WorkflowSession.fetched_bundle_id == bundle_id,
            WorkflowAction.state.in_(("queued", "running")),
        )
        .limit(1)
    )
    return active_action is not None


def _purge_retry_delay(attempts: int) -> timedelta:
    seconds = min(3600, 60 * (2 ** max(0, attempts - 1)))
    return timedelta(seconds=seconds)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def is_bundle_replayable(
    bundle: FetchedBundle,
    *,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(UTC)
    return bool(
        bundle.replayable
        and bundle.raw_available
        and bundle.state in {"confirmed", "consumed"}
        and (bundle.retention_until is None or _utc(bundle.retention_until) > _utc(current_time))
    )


def purge_fetched_bundle(
    db: Session,
    *,
    bundle_id: str,
    now: datetime | None = None,
) -> bool:
    """Purge one due bundle without changing the source workflow's outcome."""
    current_time = now or datetime.now(UTC)
    bundle = db.scalar(
        select(FetchedBundle)
        .where(FetchedBundle.id == bundle_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if bundle is None:
        raise FetchedBundleError("取数包不存在。")
    if bundle.state == "raw_purged" and not bundle.raw_available:
        return True
    if (
        not bundle.raw_available and bundle.state not in {"creating", "purge_pending"}
    ) or bundle.state not in {
        "creating",
        "ready_for_review",
        "confirmed",
        "consumed",
        "invalid",
        "purge_pending",
    }:
        return False
    if bundle.state == "creating":
        if _utc(bundle.created_at) + timedelta(minutes=15) > _utc(current_time):
            return False
    elif bundle.retention_until is None or _utc(bundle.retention_until) > _utc(current_time):
        return False
    if bundle.purge_retry_at is not None and _utc(bundle.purge_retry_at) > _utc(current_time):
        return False
    if _bundle_has_active_reference(db, bundle.id):
        return False

    if bundle.state == "creating":
        bundle.retention_until = current_time
    bundle.state = "purge_pending"
    bundle.purge_attempts += 1
    # This timestamp also acts as a short lease after the row lock is released
    # for filesystem I/O. A crashed worker can safely retry after it expires.
    bundle.purge_retry_at = current_time + timedelta(minutes=5)
    bundle.last_error = ""
    purge_attempt = bundle.purge_attempts
    storage_paths = [_bundle_storage_path(bundle)]
    owner_root = _owner_storage_root(bundle.owner_id)
    storage_paths.extend(
        path for path in owner_root.glob(f".{bundle.id}*.tmp") if path.parent == owner_root
    )
    db.commit()

    try:
        for storage_path in dict.fromkeys(storage_paths):
            _remove_tree(storage_path)
    except Exception:
        db.rollback()
        failed = db.scalar(
            select(FetchedBundle)
            .where(FetchedBundle.id == bundle_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if failed is None:
            raise FetchedBundleError("取数包不存在。") from None
        if failed.state != "purge_pending" or failed.purge_attempts != purge_attempt:
            completed_elsewhere = failed.state == "raw_purged" and not failed.raw_available
            db.rollback()
            return completed_elsewhere
        failed.state = "purge_pending"
        failed.purge_retry_at = current_time + _purge_retry_delay(failed.purge_attempts)
        failed.last_error = "原始取数包清理失败，平台将自动重试。"
        db.commit()
        return False

    db.rollback()
    purged = db.scalar(
        select(FetchedBundle)
        .where(FetchedBundle.id == bundle_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if purged is None:
        raise FetchedBundleError("取数包不存在。")
    if purged.state != "purge_pending" or purged.purge_attempts != purge_attempt:
        completed_elsewhere = purged.state == "raw_purged" and not purged.raw_available
        db.rollback()
        return completed_elsewhere
    purged.state = "raw_purged"
    purged.raw_available = False
    purged.replayable = False
    purged.purged_at = current_time
    purged.purge_retry_at = None
    purged.last_error = ""
    db.commit()
    return True


def purge_expired_bundles(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 10,
) -> int:
    current_time = now or datetime.now(UTC)
    bundle_ids = list(
        db.scalars(
            select(FetchedBundle.id)
            .where(
                or_(
                    and_(
                        FetchedBundle.raw_available.is_(True),
                        FetchedBundle.retention_until.is_not(None),
                        FetchedBundle.retention_until <= current_time,
                    ),
                    and_(
                        FetchedBundle.state == "creating",
                        FetchedBundle.created_at <= current_time - timedelta(minutes=15),
                    ),
                    and_(
                        FetchedBundle.state == "purge_pending",
                        FetchedBundle.retention_until.is_not(None),
                        FetchedBundle.retention_until <= current_time,
                    ),
                ),
                FetchedBundle.state.in_(
                    (
                        "ready_for_review",
                        "creating",
                        "confirmed",
                        "consumed",
                        "invalid",
                        "purge_pending",
                    )
                ),
                or_(
                    FetchedBundle.purge_retry_at.is_(None),
                    FetchedBundle.purge_retry_at <= current_time,
                ),
            )
            .order_by(FetchedBundle.retention_until.asc(), FetchedBundle.id.asc())
            .limit(max(1, min(int(limit), 100)))
        )
    )
    purged = 0
    for bundle_id in bundle_ids:
        if purge_fetched_bundle(db, bundle_id=bundle_id, now=current_time):
            purged += 1
    return purged


@dataclass
class FetchedBundleReplayAdapter:
    db: Session
    bundle_id: str
    owner_id: str
    source_type: Literal["replay"] = "replay"

    def export(self, dates: list[str], target: Path) -> FetchManifest:
        bundle = _owned_bundle(self.db, self.bundle_id, self.owner_id)
        if not is_bundle_replayable(bundle):
            raise FetchedBundleError("取数包当前不可回放。")
        assert_bundle_consumable(
            self.db,
            bundle_id=bundle.id,
            owner_id=self.owner_id,
            dates=dates,
        )
        members = _validated_bundle_members(bundle, dates)
        target.mkdir(parents=True, exist_ok=True)
        source_root = _bundle_storage_path(bundle)
        exported: list[FetchExportFile] = []
        for item in members:
            destination = target / item.relative_name
            shutil.copy2(source_root / item.relative_name, destination)
            exported.append(
                FetchExportFile(
                    dataset=item.dataset,  # type: ignore[arg-type]
                    reconciliation_date=item.reconciliation_date,
                    relative_name=item.relative_name,
                )
            )
        return FetchManifest(
            manifest_version=bundle.manifest_version,
            files=tuple(exported),
        )
