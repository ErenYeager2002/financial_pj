"""Private, bounded evidence archives; never an executable or replay source."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

VERSION = "ar-staging-archive-v1"
ARCHIVE_DIR = "execution-archives"
MAX_FILES = 10000
MAX_FILE_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 16 * 1024**3
MAX_MANIFEST_BYTES = 8 * 1024**2
CHUNK = 1024**2


class ArchiveError(ValueError):
    """Only fixed, safe explanations may cross the maintenance boundary."""


def _regular(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ArchiveError("暂存或归档中存在链接、目录联接或非普通文件，已保留原目录。")
    return info


def _stamp(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _walk_error(exc: OSError) -> None:
    raise ArchiveError("暂存子目录无法完整读取，未继续清理。") from exc


def inventory(root: Path) -> dict[str, list[int]]:
    _regular(root, directory=True)
    files: dict[str, list[int]] = {}
    total = 0
    entries = 0
    for folder, directories, names in os.walk(root, followlinks=False, onerror=_walk_error):
        entries += len(directories) + len(names)
        if entries > MAX_FILES:
            raise ArchiveError("暂存目录超过一万项核查上限，未截断或删除。")
        for name in directories:
            _regular(Path(folder) / name, directory=True)
        for name in names:
            path = Path(folder) / name
            info = _regular(path)
            total += info.st_size
            if info.st_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ArchiveError("暂存单文件超过 2 GiB 或总量超过 16 GiB，已保留原目录。")
            files[path.relative_to(root).as_posix()] = _stamp(info)
    return dict(sorted(files.items()))


def _retained(name: str) -> bool:
    parts = PurePosixPath(name).parts
    # Export copies follow the raw-bundle lifecycle. Keep only the derived
    # summary needed by historical range reports, never a replayable raw set.
    return "01_智云导出" not in parts or (
        parts[-1].startswith("取数摘要_") and parts[-1].endswith(".json")
    )


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def build_archive(stage: Path, destination: Path, binding: dict) -> tuple[dict, dict]:
    before = inventory(stage)
    manifest = {"schema_version": VERSION, "binding": binding, "files": {},
                "omitted_raw_files": [name for name in before if not _retained(name)]}
    # The unique attempt file is never overwritten, including after a crash.
    with destination.open("xb") as output:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            for name, stamp in before.items():
                if not _retained(name):
                    continue
                digest = hashlib.sha256()
                size = 0
                with (stage / name).open("rb") as source, archive.open("evidence/" + name, "w", force_zip64=True) as target:
                    while chunk := source.read(CHUNK):
                        size += len(chunk)
                        if size > stamp[2]:
                            raise ArchiveError("归档期间暂存文件发生变化，未清理原目录。")
                        digest.update(chunk)
                        target.write(chunk)
                if size != stamp[2]:
                    raise ArchiveError("归档期间暂存文件发生变化，未清理原目录。")
                manifest["files"][name] = {"size": size, "sha256": digest.hexdigest()}
            raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
            if len(raw) > MAX_MANIFEST_BYTES:
                raise ArchiveError("归档清单超过 8 MiB，未清理原目录。")
            archive.writestr("manifest.json", raw)
        output.flush()
        os.fsync(output.fileno())
    if inventory(stage) != before:
        raise ArchiveError("归档期间暂存目录或文件发生变化，未清理原目录。")
    reference = {"schema_version": VERSION, "path": str(destination), "sha256": _digest(destination),
                 "manifest_sha256": hashlib.sha256(raw).hexdigest(), "binding": binding}
    with open_archive(reference, destination.parent.parent) as (archive, checked):
        for name in checked["files"]:
            _consume(archive, name, checked["files"][name])
    return reference, before


@contextmanager
def open_archive(reference: dict, directory: Path):
    path = Path(str(reference.get("path") or ""))
    _regular(directory, directory=True)
    if (path.parent.parent.resolve() != directory.resolve() or not path.is_absolute()
            or path.name != "evidence.zip" or not re.fullmatch(r"[0-9a-f]{32}", path.parent.name)):
        raise ArchiveError("暂存归档不属于原任务的归档目录。")
    _regular(path.parent, directory=True)
    stamp = _stamp(_regular(path))
    if stamp[2] > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES + 64 * 1024**2:
        raise ArchiveError("暂存归档超过受控读取上限。")
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != reference.get("sha256"):
            raise ArchiveError("暂存归档实际文件的指纹不一致，不能用于历史报告或清理。")
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES + 1 or len({item.filename for item in infos}) != len(infos):
                raise ArchiveError("暂存归档包含重复文件或超过核查上限。")
            info = archive.getinfo("manifest.json")
            if info.file_size > MAX_MANIFEST_BYTES:
                raise ArchiveError("暂存归档清单超过读取上限。")
            raw = archive.read(info)
            manifest = json.loads(raw)
            if (reference.get("schema_version") != VERSION
                    or hashlib.sha256(raw).hexdigest() != reference.get("manifest_sha256")
                    or manifest.get("schema_version") != VERSION
                    or manifest.get("binding") != reference.get("binding")):
                raise ArchiveError("暂存归档的版本、业务绑定或清单指纹不一致。")
            files = manifest.get("files")
            if not isinstance(files, dict) or set(archive.namelist()) != {"manifest.json", *("evidence/" + name for name in files)}:
                raise ArchiveError("暂存归档文件与登记清单不一致。")
            total = 0
            for name, item in files.items():
                relative = PurePosixPath(name)
                if (not name or relative.is_absolute() or relative.as_posix() != name
                        or any(part in {"..", "."} or ":" in part or "\\" in part for part in relative.parts)
                        or not isinstance(item, dict) or type(item.get("size")) is not int
                        or not 0 <= item["size"] <= MAX_FILE_BYTES
                        or archive.getinfo("evidence/" + name).file_size != item["size"]):
                    raise ArchiveError("暂存归档包含非法文件路径或文件大小。")
                total += item["size"]
            if total > MAX_TOTAL_BYTES:
                raise ArchiveError("暂存归档展开大小超过 16 GiB。")
            yield archive, manifest
        if _stamp(_regular(path)) != stamp:
            raise ArchiveError("读取期间暂存归档发生变化，不能采用本次读取结果。")


def _consume(archive: zipfile.ZipFile, name: str, item: dict, target=None) -> None:
    digest = hashlib.sha256()
    size = 0
    with archive.open("evidence/" + name) as source:
        while chunk := source.read(CHUNK):
            size += len(chunk)
            if size > item["size"]:
                raise ArchiveError("归档文件展开后大小超出原清单。")
            digest.update(chunk)
            if target is not None:
                target.write(chunk)
    if size != item["size"] or digest.hexdigest() != item.get("sha256"):
        raise ArchiveError("归档内文件与原暂存文件的大小或指纹不一致。")


def copy_report_inputs(reference: dict, directory: Path, date: str, output: Path, exports: Path) -> None:
    token = date.replace("-", "")
    with open_archive(reference, directory) as (archive, manifest):
        for name, item in manifest["files"].items():
            relative = PurePosixPath(name)
            target_dir = None
            if relative.parent.as_posix() == "04_产出" and (
                relative.name == f"判定结果_{token}.json" or
                (relative.suffix == ".xlsx" and any(relative.name.startswith(f"{prefix}_{token}")
                                                    for prefix in ("变更清单", "订单写入差异")))
            ):
                target_dir = output
            elif name == f"01_智云导出/取数摘要_{token}.json":
                target_dir = exports
            if target_dir is None:
                continue
            target = target_dir / relative.name
            if target.exists():
                _regular(target)
                if _digest(target) != item["sha256"]:
                    raise ArchiveError("范围报告输入文件名重复且内容不一致。")
            else:
                with target.open("xb") as handle:
                    _consume(archive, name, item, handle)


def remove_quarantine(root: Path, directory: Path, expected: dict, heartbeat) -> None:
    """Delete only a fenced sibling of the registered archive, never staging."""
    if root.parent.resolve() != directory.resolve() or not root.name.endswith(".purging"):
        raise ArchiveError("暂存清理目标不属于原任务的隔离目录。")
    _regular(directory, directory=True)
    if not root.exists():
        return
    remaining = inventory(root)  # Also rejects reparse points throughout.
    if any(expected.get(name) != stamp for name, stamp in remaining.items()):
        raise ArchiveError("清理隔离目录出现新增或变化文件，未继续删除，证据归档保留。")
    for folder, directories, names in os.walk(root, topdown=False, followlinks=False, onerror=_walk_error):
        for name in names:
            heartbeat()
            path = Path(folder) / name
            _regular(path)
            path.unlink(missing_ok=True)
        for name in directories:
            heartbeat()
            path = Path(folder) / name
            _regular(path, directory=True)
            path.rmdir()
    heartbeat()
    root.rmdir()
