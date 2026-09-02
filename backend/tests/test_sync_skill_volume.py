from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync_skill_volume.py"
SPEC = importlib.util.spec_from_file_location("sync_skill_volume", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _skill(root: Path, skill_id: str, version: str, code: str) -> Path:
    target = root / skill_id
    target.mkdir(parents=True)
    (target / "tool.yaml").write_text(
        yaml.safe_dump({"id": skill_id, "version": version}, sort_keys=False),
        encoding="utf-8",
    )
    (target / "worker.py").write_text(code, encoding="utf-8")
    return target


def test_sync_installs_and_upgrades_only_newer_versions(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source = _skill(source_root, "demo", "1.0.0", "old")

    assert MODULE.sync_skill(source, target_root) == "installed demo 1.0.0"
    assert (target_root / "demo" / "worker.py").read_text("utf-8") == "old"

    (source / "tool.yaml").write_text("id: demo\nversion: 1.1.0\n", encoding="utf-8")
    (source / "worker.py").write_text("new", encoding="utf-8")
    assert MODULE.sync_skill(source, target_root) == "upgraded demo 1.0.0 -> 1.1.0"
    assert (target_root / "demo" / "worker.py").read_text("utf-8") == "new"


def test_sync_rejects_changed_content_without_version_bump(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source = _skill(source_root, "demo", "1.0.0", "original")
    MODULE.sync_skill(source, target_root)
    (source / "worker.py").write_text("changed", encoding="utf-8")

    with pytest.raises(RuntimeError, match="版本号未升级"):
        MODULE.sync_skill(source, target_root)
    assert (target_root / "demo" / "worker.py").read_text("utf-8") == "original"


def test_sync_never_downgrades_runtime_release(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source = _skill(source_root, "demo", "1.0.0", "image")
    _skill(target_root, "demo", "2.0.0", "published")

    assert MODULE.sync_skill(source, target_root) == "kept-newer demo 2.0.0"
    assert (target_root / "demo" / "worker.py").read_text("utf-8") == "published"


def test_sync_all_validates_every_selected_skill_before_replacing(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    _skill(source_root, "alpha", "2.0.0", "new-alpha")
    _skill(target_root, "alpha", "1.0.0", "old-alpha")
    beta = _skill(source_root, "beta", "1.0.0", "changed-beta")
    _skill(target_root, "beta", "1.0.0", "old-beta")

    with pytest.raises(RuntimeError, match="版本号未升级"):
        MODULE.sync_all(source_root, target_root, ["alpha", "beta"])
    assert (target_root / "alpha" / "worker.py").read_text("utf-8") == "old-alpha"
    assert (target_root / "beta" / "worker.py").read_text("utf-8") == "old-beta"
    assert beta.is_dir()
