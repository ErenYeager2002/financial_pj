"""Checks for fixed ordinary-task prerequisites, before any adapter starts."""
from .authorization import ExecutionPhase


class ExecutionPreconditionFailed(RuntimeError):
    code = "CONFIRMATION_INVALID"

    def __init__(self, phase):
        self.phase = ExecutionPhase(phase)
        super().__init__("任务确认记录缺失或与固定执行快照不一致，未启动执行器。")


def assert_run_confirmation(run, manifest, phase):
    """Queue state alone is never evidence of a required user confirmation.

    The caller owns the global/task lock and reads the current task row. A past
    confirmer's current role is not reconstructed: current execution-owner
    authorization is checked separately at the same claim/start boundary.
    """
    required = manifest.risk.requires_confirmation
    if run.confirmation_required != required or (
        required and (not run.confirmed_by.strip() or run.confirmed_at is None)
    ):
        raise ExecutionPreconditionFailed(phase)


class ExecutionSnapshotInvalid(ExecutionPreconditionFailed):
    code = "SKILL_SNAPSHOT_INVALID"

    def __init__(self):
        self.phase = ExecutionPhase.START
        RuntimeError.__init__(self, "任务固定的 Skill 执行快照缺失或已经变化，未启动执行器。")


def assert_skill_snapshot(run, manifest, skill_dir):
    """Validate the task's immutable package, never the currently published revision.

    Registry metadata is not part of tool.yaml. All declared manifest fields and
    extension fields remain compared, alongside the registry's directory digest.
    Filesystem writes by an external process after this check are not atomic with
    process startup; the deployment must continue protecting task snapshot paths.
    """
    from pathlib import Path
    import yaml
    from ...registry import SkillManifest, hash_skill_directory

    try:
        path = skill_dir / "tool.yaml"
        if (
            not skill_dir.is_dir() or skill_dir.is_symlink()
            or any(item.is_symlink() for item in skill_dir.rglob("*"))
            or Path(run.manifest_path).resolve() != path.resolve()
            or run.skill_hash != hash_skill_directory(skill_dir)
        ):
            raise ExecutionSnapshotInvalid()
        on_disk = SkillManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        metadata = {"skill_hash", "commit_sha", "source"}
        if (
            on_disk.model_dump(exclude=metadata) != manifest.model_dump(exclude=metadata)
            or manifest.id != run.skill_id
            or manifest.version != run.skill_version
            or manifest.handler.adapter != run.adapter
        ):
            raise ExecutionSnapshotInvalid()
    except (OSError, ValueError, yaml.YAMLError):
        raise ExecutionSnapshotInvalid() from None


class ExecutionInputChanged(ExecutionPreconditionFailed):
    code = "INPUT_SNAPSHOT_CHANGED"

    def __init__(self, phase):
        self.phase = ExecutionPhase(phase)
        RuntimeError.__init__(self, "任务指令、参数或执行配置与提交时的固定快照不一致，请重新创建任务。")


def assert_run_input_snapshot(run, phase):
    import json
    from .input_snapshot import input_snapshot_hash

    try:
        actual = input_snapshot_hash(run.parameters_json, json.loads(run.files_json), run.skill_hash)
    except (TypeError, ValueError):
        raise ExecutionInputChanged(phase) from None
    if not run.input_hash or actual != run.input_hash:
        raise ExecutionInputChanged(phase)
