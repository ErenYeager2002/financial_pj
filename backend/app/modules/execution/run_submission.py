"""Ordinary Run application adapter for scoped, durable submission receipts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...authorization import refresh_active_user, assert_skill_permission
from ...model_service import resolve_runtime_config
from ...models import RunRecord
from ...orchestrator import config_extra_body
from ...registry import RegisteredSkill, SkillManifest, hash_skill_directory
from ...resource_policy import run_root
from ...settings import settings
from .canonical import validate_request_key
from .idempotency import Scope, Operation, IdempotencyConflict, ReservationLost, read
from .submission import prepare_submission, persist_submission, SubmissionInProgress, SubmissionRejected, SubmissionRecoveryOnly


def _model_pin(config):
    if config is None:
        return None
    # Detect a changed endpoint/protocol/options without storing endpoint secrets.
    options = json.dumps({"endpoint":config.base_url, "protocol":config.protocol,
                          "options":config_extra_body(config)}, sort_keys=True, ensure_ascii=False)
    return {"connection_id":config.connection_id, "provider":config.provider,
            "model":config.model, "options_sha256":hashlib.sha256(options.encode()).hexdigest()}


def _canonicalize(submitted, pin):
    result = deepcopy(submitted)
    schema = pin["skill"]["manifest"]["input_schema"]
    parameters = result["parameters"]
    for key, spec in schema.get("properties", {}).items():
        if key not in parameters and "default" in spec:
            parameters[key] = deepcopy(spec["default"])
    return result


def assert_standard_submission(manifest):
    if (manifest.status != "published" or manifest.handler.adapter == "workflow"
            or manifest.risk.level != "read_only" or manifest.risk.modifies_uploaded_files):
        raise HTTPException(403, "该工具不能通过标准只读任务入口执行。")


def submit_run(db, request, user, *, operation=Operation.RUN_CREATE, on_persist=None, standard_only=False):
    """Endpoint must finish its read phase first; caller owns final commit."""
    from ... import run_service
    engine = getattr(db.get_bind(), "engine", db.get_bind())
    scope = Scope(user.user_id, user.department_id, operation)
    key = request.idempotency_key or str(uuid4())
    try:
        validate_request_key(key)
    except ValueError as exc:
        raise HTTPException(422, "提交标识格式无效。") from exc
    bare = request.model_copy(update={"idempotency_key":None}, deep=True)

    def authorize(session):
        active = refresh_active_user(session, user)
        assert_skill_permission(session, active, request.skill_id)
        if request.files:
            assert_skill_permission(session, active, request.skill_id, "can_upload")
        return active

    def select_pin(session):
        # Old rows lack the original canonical request. Never guess a matching
        # resource or create a second execution for a known historical key.
        legacy_id = session.scalar(select(RunRecord.id).where(
            RunRecord.owner_id == scope.owner_id,
            RunRecord.department_id == scope.department_id,
            RunRecord.adapter != "native", RunRecord.idempotency_key == key,
        ).limit(1))
        if legacy_id is not None:
            raise HTTPException(409, {"code":"LEGACY_SUBMISSION_UNVERIFIED",
                "message":"该提交标识已有历史任务，缺少可核验的原始提交记录。请先核查历史任务，系统未创建新任务。"})
        skill, active, config = run_service._resolve_preparation_context(session, bare, authorize(session))
        if standard_only:
            assert_standard_submission(skill.manifest)
        files, file_hash = run_service.validate_files(session, skill, request.files, active)
        return {"skill":skill.model_dump(mode="json"), "model":_model_pin(config),
                "request":bare.model_dump(mode="json", exclude={"idempotency_key"}),
                "files":files, "file_hash":file_hash}

    def external_prepare(pin):
        skill = RegisteredSkill.model_validate(pin["skill"])
        if standard_only:
            assert_standard_submission(skill.manifest)
        with Session(engine) as session:
            active = authorize(session)
            chosen = pin["model"]
            config = resolve_runtime_config(session, active,
                chosen["connection_id"] if chosen else bare.model_connection_id,
                chosen["model"] if chosen else bare.model)
            if _model_pin(config) != chosen:
                raise HTTPException(409, "模型配置已经变化，请重新提交。")
            files, file_hash = run_service.validate_files(session, skill, request.files, active)
            if files != pin["files"] or file_hash != pin["file_hash"]:
                raise HTTPException(409, "输入文件已经变化，请重新提交。")
        # This Session is only a bind provider; prepare_run owns short reads and
        # performs model parsing and staging after those reads are closed.
        with Session(engine) as session:
            return run_service.prepare_run(session, bare, active, context=(skill, active, config))

    def validate(session, prepared):
        run = prepared.run
        if run.skill_id != request.skill_id:
            raise HTTPException(409, "提交记录与任务工具不一致。")
        snapshot_root = run_root(user.user_id, run.id) / "skill"
        if snapshot_root.is_symlink():
            raise HTTPException(409, "任务快照路径无效。")
        expected = (snapshot_root / "tool.yaml").resolve()
        if Path(run.manifest_path).resolve() != expected:
            raise HTTPException(409, "任务快照路径无效。")
        directory = expected.parent
        if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob("*")) or hash_skill_directory(directory) != run.skill_hash:
            raise HTTPException(409, "任务快照内容已经变化。")
        skill = RegisteredSkill(manifest=SkillManifest.model_validate(json.loads(run.manifest_snapshot)),
            directory=directory, manifest_path=expected, skill_hash=run.skill_hash,
            commit_sha=run.skill_commit, source="submission-snapshot")
        if standard_only:
            assert_standard_submission(skill.manifest)
        run_service._revalidate_prepared_run(session, prepared, bare, authorize(session), pinned_skill=skill)

    def load_bound(session, kind, run_id):
        active = authorize(session)
        run = session.get(RunRecord, run_id, populate_existing=True)
        if (kind != "run" or run is None or run.owner_id != active.user_id
                or run.department_id != active.department_id or run.skill_id != request.skill_id):
            raise HTTPException(404, "原任务不存在或不可访问。")
        if standard_only:
            assert_standard_submission(SkillManifest.model_validate(json.loads(run.manifest_snapshot)))
        return run

    try:
        ticket = prepare_submission(engine, scope=scope, key=key,
            submitted=bare.model_dump(mode="json", exclude={"idempotency_key"}),
            authorize=authorize, select_pin=select_pin, prepare=external_prepare,
            canonicalize=_canonicalize, replay_only=settings.submission_replay_only)
        return persist_submission(db, ticket, authorize=authorize,
                                  validate_prepared=validate, load_bound=load_bound, on_persist=on_persist,
                                  replay_only=settings.submission_replay_only)
    except SubmissionRecoveryOnly as exc:
        detail = {"code":"SUBMISSION_RECOVERY_ONLY", "message":"平台处于提交恢复模式，暂不接受新任务。已创建的任务仍可查询。"}
        if exc.receipt_id is not None:
            detail["request_id"] = exc.receipt_id
        raise HTTPException(503, detail) from exc
    except IdempotencyConflict as exc:
        raise HTTPException(409, {"code":"IDEMPOTENCY_CONFLICT", "message":"同一提交标识不能用于不同内容。"}) from exc
    except SubmissionInProgress as exc:
        raise HTTPException(409, {"code":"SUBMISSION_IN_PROGRESS", "request_id":exc.receipt_id}) from exc
    except (SubmissionRejected, ReservationLost) as exc:
        raise HTTPException(409, {"code":"SUBMISSION_NOT_READY", "message":"提交状态已变化，请使用原提交标识查询或重试。"}) from exc


def prepare_retry_submission_request(db, source, user):
    """One retry intent per source Run; network retries reuse its frozen request.

    Once reserved, publication/input retention changes must not make a committed
    retry unreachable. Current identity and tool permission are always checked.
    The resource loader still verifies exact scope before returning the new Run.
    """
    from ...run_service import prepare_retry_request
    from ...schemas import RunCreate
    active = refresh_active_user(db, user)
    assert_skill_permission(db, active, source.skill_id)
    scope = Scope(active.user_id, active.department_id, Operation.RUN_RETRY)
    key = "retry:" + source.id
    receipt = read(db, scope, key)
    if receipt is None:
        return prepare_retry_request(db, source, active)
    pin = json.loads(receipt.pinned_revision_json)
    if not isinstance(pin.get("request"), dict):
        raise HTTPException(409, "重试登记缺少固定输入，请管理员核查。")
    request = RunCreate.model_validate({**pin["request"], "idempotency_key":key})
    if request.skill_id != source.skill_id:
        raise HTTPException(409, "重试登记与原任务不一致。")
    return request
