from types import SimpleNamespace
from fastapi import HTTPException
import pytest
from app import run_service


@pytest.mark.parametrize("change", ["source", "staging", "link", "source_reverted"])
def test_snapshot_copy_must_match_pinned_revision(tmp_path, monkeypatch, change):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.yaml").write_text("original")
    pinned = run_service.hash_skill_directory(source)
    target = tmp_path / "task"
    monkeypatch.setattr(run_service, "run_root", lambda *a: target)
    original_copy = run_service.shutil.copytree
    def copy(src, dst, **kwargs):
        if change == "source_reverted":
            (source / "tool.yaml").write_text("changed")
        result = original_copy(src, dst, **kwargs)
        if change == "source":
            (source / "tool.yaml").write_text("changed")
        elif change == "staging":
            (dst / "tool.yaml").write_text("changed")
        elif change == "link":
            (dst / "link").symlink_to(source / "tool.yaml")
        elif change == "source_reverted":
            (source / "tool.yaml").write_text("original")
        return result
    monkeypatch.setattr(run_service.shutil, "copytree", copy)
    with pytest.raises(HTTPException) as error:
        run_service._snapshot_skill(SimpleNamespace(directory=source, skill_hash=pinned), "owner", "run")
    assert error.value.status_code == (422 if change == "link" else 409)
    assert not (target / "skill").exists()
    assert len(list(target.glob("skill.staging-*"))) == 1


def test_stale_registry_pin_rejected_before_copy(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.yaml").write_text("original")
    pinned = run_service.hash_skill_directory(source)
    (source / "tool.yaml").write_text("changed")
    target = tmp_path / "task"
    monkeypatch.setattr(run_service, "run_root", lambda *a: target)
    with pytest.raises(HTTPException) as error:
        run_service._snapshot_skill(SimpleNamespace(directory=source, skill_hash=pinned), "owner", "run")
    assert error.value.status_code == 409
    assert not list(target.glob("skill*"))
