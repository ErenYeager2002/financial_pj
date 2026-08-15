from __future__ import annotations

import inspect
import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .assistant_profile_service import resolve_assistant_config
from .auth import UserContext
from .authorization import allowed_skill_ids, assert_skill_permission
from .contracts import SkillSummary, TaskDraft
from .model_providers import chat_completion_request
from .models import FileRecord, ModelTraceRecord, RunRecord, TaskDraftRecord
from .orchestrator import config_extra_body, interpret_parameters
from .registry import RegisteredSkill, registry
from .resource_policy import assert_owner
from .run_service import confirm_run, create_run, validate_files
from .schemas import RunCreate
from .schemas_assistant import AssistantRecommendation, TaskDraftUpdate
from .settings import settings
from .storage import sha256_file

RecommendationTrace = dict[str, int | str]
RecommendationClient = Callable[..., AssistantRecommendation]
_MIN_CONFIDENCE_PERCENT = 60


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _confidence_percent(confidence: float) -> int:
    return max(0, min(100, int(confidence * 100)))


def _draft_is_ready(confidence: int, missing: list[str]) -> bool:
    return confidence >= _MIN_CONFIDENCE_PERCENT and not missing


def _safe_skills(db: Session, user: UserContext) -> list[RegisteredSkill]:
    allowed = allowed_skill_ids(db, user, "can_create_draft")
    return [
        item
        for item in registry.list(include_disabled=False)
        if (user.is_admin or item.manifest.id in allowed)
        and item.manifest.handler.adapter != "workflow"
        and item.manifest.risk.level == "read_only"
        and not item.manifest.risk.modifies_uploaded_files
    ]


def _skill_summary(skill: RegisteredSkill) -> SkillSummary:
    return SkillSummary.model_validate(skill.employee_dict(include_schema=False))


def _recommendation_payload(
    skills: list[RegisteredSkill],
    message: str,
    files: dict[str, FileRecord],
    model: str,
) -> dict[str, Any]:
    skill_ids = [item.manifest.id for item in skills]
    catalog = [
        {
            "id": item.manifest.id,
            "name": item.manifest.name,
            "description": item.manifest.description,
            "file_inputs": [entry.model_dump() for entry in item.manifest.file_inputs],
            "input_schema": item.manifest.input_schema,
        }
        for item in skills
    ]
    file_catalog = [
        {
            "alias": alias,
            "name": record.original_name,
            "size_bytes": record.size_bytes,
            "extension": Path(record.original_name).suffix.lower(),
        }
        for alias, record in files.items()
    ]
    tool = {
        "type": "function",
        "function": {
            "name": "prepare_task_draft",
            "description": "从授权 Skill 中推荐一个能力并生成不可执行任务草稿",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["skill_id", "confidence", "parameters", "file_roles"],
                "properties": {
                    "skill_id": {"type": "string", "enum": skill_ids},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "candidates": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string", "enum": skill_ids},
                    },
                    "parameters": {"type": "object"},
                    "file_roles": {"type": "object"},
                    "clarification": {"type": "string"},
                    "confirmation_text": {"type": "string"},
                },
            },
        },
    }
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你只负责从给定授权 Skill 中推荐能力并生成不可执行草稿。"
                    "不得生成路径、命令、SQL、凭据或未提供的文件标识。"
                    "文件只能使用 file_catalog 中的 alias。低于0.60置信度时必须提出澄清问题。"
                    f"\nSkill目录：{_json(catalog)}\n可选文件：{_json(file_catalog)}"
                ),
            },
            {"role": "user", "content": message},
        ],
        "tools": [tool],
        "tool_choice": {"type": "function", "function": {"name": "prepare_task_draft"}},
        "temperature": 0,
    }


def _trace_metrics(trace: RecommendationTrace, started: float) -> None:
    trace["duration_ms"] = max(0, round((time.perf_counter() - started) * 1000))


def _usage_tokens(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0
    return (
        max(0, int(usage.get("prompt_tokens") or 0)),
        max(0, int(usage.get("completion_tokens") or 0)),
    )


def _call_recommender(
    payload: dict[str, Any],
    config,
    trace: RecommendationTrace | None = None,
) -> AssistantRecommendation:
    payload.update(config_extra_body(config))
    started = time.perf_counter()
    input_tokens = 0
    output_tokens = 0
    skill_schema = payload["tools"][0]["function"]["parameters"]["properties"]["skill_id"]
    allowed_ids = set(skill_schema.get("enum") or [])
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = chat_completion_request(
                config.provider,
                config.base_url,
                config.api_key,
                payload,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("模型响应必须是对象")
            input_tokens, output_tokens = _usage_tokens(data)
            calls = data["choices"][0]["message"].get("tool_calls") or []
            if len(calls) != 1 or calls[0]["function"]["name"] != "prepare_task_draft":
                raise ValueError("模型没有返回指定工具调用")
            recommendation = AssistantRecommendation.model_validate_json(
                calls[0]["function"]["arguments"]
            )
            returned_ids = {recommendation.skill_id, *recommendation.candidates}
            if not returned_ids <= allowed_ids:
                raise ValueError("模型返回了目录之外的 Skill 标识")
            if trace is not None:
                trace.update(
                    status="succeeded",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    failure_code="",
                )
                _trace_metrics(trace, started)
            return recommendation
        except httpx.HTTPError as exc:
            last_error = exc
            break
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            last_error = exc
            if attempt == 0:
                payload["messages"].append(
                    {
                        "role": "system",
                        "content": (
                            "上一响应无效。必须调用 prepare_task_draft，"
                            "skill_id 和 candidates 只能逐字复制以下 ID："
                            f"{_json(sorted(allowed_ids))}"
                        ),
                    }
                )
                continue
            break
    if trace is not None:
        trace.update(
            status="failed",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            failure_code=type(last_error).__name__[:64] if last_error else "unknown",
        )
        _trace_metrics(trace, started)
    raise HTTPException(status_code=502, detail="AI 助手返回了无效的结构化结果。") from last_error


def _invoke_recommender(
    client: RecommendationClient,
    payload: dict[str, Any],
    config: Any,
    trace: RecommendationTrace,
) -> AssistantRecommendation:
    """兼容两参数测试替身；生产客户端通过第三参数回填真实调用指标。"""
    parameters = inspect.signature(client).parameters.values()
    accepts_trace = any(item.kind == inspect.Parameter.VAR_POSITIONAL for item in parameters)
    accepts_trace = accepts_trace or len(
        [
            item
            for item in parameters
            if item.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
    ) >= 3
    started = time.perf_counter()
    try:
        recommendation = (
            client(payload, config, trace)
            if accepts_trace
            else client(payload, config)
        )
    except Exception as exc:
        trace.setdefault("status", "failed")
        trace.setdefault("input_tokens", 0)
        trace.setdefault("output_tokens", 0)
        trace.setdefault("failure_code", type(exc).__name__[:64])
        trace.setdefault(
            "duration_ms", max(0, round((time.perf_counter() - started) * 1000))
        )
        raise
    trace.setdefault("status", "succeeded")
    trace.setdefault("input_tokens", 0)
    trace.setdefault("output_tokens", 0)
    trace.setdefault("failure_code", "")
    trace.setdefault(
        "duration_ms", max(0, round((time.perf_counter() - started) * 1000))
    )
    return recommendation


def _model_trace(
    user: UserContext,
    config: Any,
    trace: RecommendationTrace,
) -> ModelTraceRecord:
    return ModelTraceRecord(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        department_id=user.department_id,
        connection_id=config.connection_id,
        purpose="assistant_recommendation",
        provider=config.provider,
        model=config.model,
        status=str(trace.get("status", "failed")),
        duration_ms=max(0, int(trace.get("duration_ms", 0))),
        input_tokens=max(0, int(trace.get("input_tokens", 0))),
        output_tokens=max(0, int(trace.get("output_tokens", 0))),
        failure_code=str(trace.get("failure_code", "unknown"))[:64],
    )


def _selected_files(
    db: Session,
    user: UserContext,
    file_ids: list[str],
) -> dict[str, FileRecord]:
    if len(file_ids) != len(set(file_ids)):
        raise HTTPException(status_code=422, detail="同一文件不能重复选择。")
    result: dict[str, FileRecord] = {}
    for index, file_id in enumerate(file_ids, start=1):
        record = db.get(FileRecord, file_id)
        if not record or record.kind != "input":
            raise HTTPException(status_code=404, detail="所选上传文件不存在。")
        assert_owner(record.owner_id, user, "上传文件", record.department_id)
        result[f"F{index}"] = record
    return result


def _bindings_from_aliases(
    recommendation: AssistantRecommendation,
    selected: dict[str, FileRecord],
) -> dict[str, str | list[str]]:
    bindings: dict[str, str | list[str]] = {}
    used: set[str] = set()
    for role, raw in recommendation.file_roles.items():
        aliases = raw if isinstance(raw, list) else [raw]
        if any(alias not in selected for alias in aliases):
            raise HTTPException(status_code=502, detail="AI 助手引用了未提供的文件。")
        if any(alias in used for alias in aliases):
            raise HTTPException(status_code=502, detail="AI 助手重复分配了同一文件。")
        used.update(aliases)
        ids = [selected[alias].id for alias in aliases]
        bindings[role] = ids if isinstance(raw, list) else ids[0]
    return bindings


def _validate_parameters(
    skill: RegisteredSkill,
    parameters: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    values, missing, _, _ = interpret_parameters(skill, "", parameters, None)
    errors = sorted(
        Draft202012Validator(skill.manifest.input_schema).iter_errors(values), key=str
    )
    if errors:
        raise HTTPException(status_code=502, detail="AI 助手生成的参数未通过 Skill 校验。")
    for key, constraint in skill.manifest.safety_constraints.items():
        if key not in values:
            continue
        value = values[key]
        if constraint.minimum is not None and value < constraint.minimum:
            raise HTTPException(status_code=502, detail="AI 助手生成的参数超出安全范围。")
        if constraint.maximum is not None and value > constraint.maximum:
            raise HTTPException(status_code=502, detail="AI 助手生成的参数超出安全范围。")
    return values, missing


def _validate_draft_files(
    db: Session,
    user: UserContext,
    skill: RegisteredSkill,
    bindings: dict[str, str | list[str]],
) -> tuple[dict[str, str | list[str]], dict[str, str], list[str]]:
    specs = {item.role: item for item in skill.manifest.file_inputs}
    if unknown := sorted(set(bindings) - set(specs)):
        raise HTTPException(status_code=502, detail=f"AI 助手生成了未知文件角色：{unknown}")
    normalized: dict[str, str | list[str]] = {}
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for role, spec in specs.items():
        raw = bindings.get(role)
        ids = raw if isinstance(raw, list) else ([raw] if raw else [])
        if spec.required and len(ids) < spec.min_files:
            missing.append(spec.name)
        if not spec.multiple and len(ids) > 1:
            raise HTTPException(status_code=502, detail=f"{spec.name}只能选择一个文件。")
        records: list[FileRecord] = []
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            if not record or record.kind != "input":
                raise HTTPException(status_code=422, detail="草稿引用的上传文件不存在。")
            assert_owner(record.owner_id, user, "上传文件", record.department_id)
            suffix = Path(record.original_name).suffix.lower().lstrip(".")
            allowed = [item.lower().lstrip(".") for item in spec.extensions]
            if allowed and suffix not in allowed:
                raise HTTPException(status_code=422, detail=f"{spec.name}不支持所选文件格式。")
            if spec.max_size_mb and record.size_bytes > spec.max_size_mb * 1024 * 1024:
                raise HTTPException(status_code=422, detail=f"{spec.name}超过大小限制。")
            records.append(record)
            hashes[record.id] = record.sha256
        normalized[role] = [item.id for item in records] if spec.multiple else (
            records[0].id if records else ""
        )
    return normalized, hashes, missing


def _draft_read(record: TaskDraftRecord) -> TaskDraft:
    return TaskDraft(
        id=record.id,
        owner_id=record.owner_id,
        skill_id=record.skill_id,
        skill_name=record.skill_name,
        skill_version=record.skill_version,
        state=record.state,
        source=record.source,
        message=record.message,
        confidence=record.confidence / 100,
        candidates=[
            SkillSummary.model_validate(item)
            for item in _load(record.candidates_json, [])
        ],
        parameters=_load(record.parameters_json, {}),
        files=_load(record.files_json, {}),
        file_hashes=_load(record.file_hashes_json, {}),
        missing_inputs=_load(record.missing_inputs_json, []),
        validation_warnings=_load(record.validation_warnings_json, []),
        requires_confirmation=record.requires_confirmation,
        requires_approval=record.requires_approval,
        clarification=record.clarification,
        confirmation_text=record.confirmation_text,
        run_id=record.run_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
    )


def _get_owned_draft(db: Session, draft_id: str, user: UserContext) -> TaskDraftRecord:
    record = db.get(TaskDraftRecord, draft_id)
    if not record or record.owner_id != user.user_id:
        raise HTTPException(status_code=404, detail="任务草稿不存在。")
    if record.state not in {"consumed", "expired"} and record.expires_at < _now():
        record.state = "expired"
        db.commit()
    return record


def prepare_task_draft(
    db: Session,
    user: UserContext,
    message: str,
    file_ids: list[str],
    recommender: RecommendationClient | None = None,
) -> TaskDraft:
    skills = _safe_skills(db, user)
    if not skills:
        raise HTTPException(status_code=403, detail="当前账号没有可用于任务草稿的 Skill。")
    selected = _selected_files(db, user, file_ids)
    config = resolve_assistant_config(db, user)
    trace: RecommendationTrace = {}
    try:
        recommendation = _invoke_recommender(
            recommender or _call_recommender,
            _recommendation_payload(skills, message, selected, config.model),
            config,
            trace,
        )
    except Exception:
        db.add(_model_trace(user, config, trace))
        db.commit()
        raise

    # 模型调用事实先独立保存。后续业务校验拒绝结果时，该记录合法保持无父级。
    model_trace = _model_trace(user, config, trace)
    db.add(model_trace)
    db.commit()
    by_id = {item.manifest.id: item for item in skills}
    skill = by_id.get(recommendation.skill_id)
    if not skill:
        raise HTTPException(status_code=502, detail="AI 助手推荐了未授权或不可用的 Skill。")
    assert_skill_permission(db, user, skill.manifest.id, "can_create_draft")
    candidate_ids = [recommendation.skill_id, *recommendation.candidates]
    if any(item not in by_id for item in candidate_ids):
        raise HTTPException(status_code=502, detail="AI 助手返回了未授权候选 Skill。")
    candidate_limit = 1 if recommendation.confidence >= 0.85 else 3
    unique_candidates = list(dict.fromkeys(candidate_ids))[:candidate_limit]
    parameters, missing_parameters = _validate_parameters(skill, recommendation.parameters)
    bindings = _bindings_from_aliases(recommendation, selected)
    files, hashes, missing_files = _validate_draft_files(db, user, skill, bindings)
    missing = [*missing_parameters, *missing_files]
    warnings = []
    assigned_ids = {
        item
        for value in files.values()
        for item in (value if isinstance(value, list) else [value])
        if item
    }
    if unused := [
        record.original_name
        for record in selected.values()
        if record.id not in assigned_ids
    ]:
        warnings.append(f"有 {len(unused)} 个所选文件未分配到文件角色。")
    confidence = _confidence_percent(recommendation.confidence)
    if confidence < _MIN_CONFIDENCE_PERCENT and not recommendation.clarification:
        raise HTTPException(status_code=502, detail="低置信度推荐缺少澄清问题。")
    ready = _draft_is_ready(confidence, missing)
    now = _now()
    record = TaskDraftRecord(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_hash=skill.skill_hash,
        state="ready" if ready else "draft",
        source="assistant",
        message=message,
        confidence=confidence,
        candidates_json=_json(
            [
                _skill_summary(by_id[item]).model_dump(mode="json")
                for item in unique_candidates
            ]
        ),
        parameters_json=_json(parameters),
        files_json=_json(files),
        file_hashes_json=_json(hashes),
        missing_inputs_json=_json(missing),
        validation_warnings_json=_json(warnings),
        clarification=recommendation.clarification,
        confirmation_text=recommendation.confirmation_text,
        requires_confirmation=True,
        requires_approval=skill.manifest.risk.requires_approval,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(minutes=settings.task_draft_ttl_minutes),
    )
    db.add(record)
    db.flush()
    model_trace.task_draft_id = record.id
    return _draft_read(record)


def get_task_draft(db: Session, draft_id: str, user: UserContext) -> TaskDraft:
    return _draft_read(_get_owned_draft(db, draft_id, user))


def update_task_draft(
    db: Session,
    draft_id: str,
    user: UserContext,
    body: TaskDraftUpdate,
) -> TaskDraft:
    record = _get_owned_draft(db, draft_id, user)
    if record.state in {"expired", "consumed"}:
        raise HTTPException(status_code=409, detail="任务草稿已经过期或使用。")
    skill = registry.get(record.skill_id)
    if not skill or skill.skill_hash != record.skill_hash:
        raise HTTPException(status_code=409, detail="Skill 版本已经变化，请重新生成草稿。")
    assert_skill_permission(db, user, record.skill_id, "can_create_draft")
    parameters = (
        body.parameters
        if body.parameters is not None
        else _load(record.parameters_json, {})
    )
    files = body.files if body.files is not None else _load(record.files_json, {})
    parameters, missing_parameters = _validate_parameters(skill, parameters)
    files, hashes, missing_files = _validate_draft_files(db, user, skill, files)
    missing = [*missing_parameters, *missing_files]
    record.parameters_json = _json(parameters)
    record.files_json = _json(files)
    record.file_hashes_json = _json(hashes)
    record.missing_inputs_json = _json(missing)
    record.state = "ready" if _draft_is_ready(record.confidence, missing) else "draft"
    record.updated_at = _now()
    db.flush()
    return _draft_read(record)


def confirm_task_draft(
    db: Session,
    draft_id: str,
    user: UserContext,
) -> RunRecord:
    record = _get_owned_draft(db, draft_id, user)
    if record.state == "consumed" and record.run_id:
        run = db.get(RunRecord, record.run_id)
        if run:
            return run
    if record.state != "ready":
        raise HTTPException(status_code=409, detail="任务草稿尚未满足确认条件。")
    skill = registry.get(record.skill_id)
    if (
        not skill
        or skill.skill_hash != record.skill_hash
        or skill.manifest.version != record.skill_version
    ):
        raise HTTPException(status_code=409, detail="Skill 版本已经变化，请重新生成草稿。")
    assert_skill_permission(db, user, record.skill_id, "can_create_draft")
    assert_skill_permission(db, user, record.skill_id, "can_run")
    if skill.manifest.risk.requires_approval or skill.manifest.risk.level != "read_only":
        raise HTTPException(status_code=409, detail="该任务需要审批，当前阶段不能从助手直接执行。")
    parameters = _load(record.parameters_json, {})
    _validate_parameters(skill, parameters)
    files = _load(record.files_json, {})
    validate_files(db, skill, files, user)
    expected_hashes = _load(record.file_hashes_json, {})
    for file_id, expected in expected_hashes.items():
        stored = db.get(FileRecord, file_id)
        if not stored:
            raise HTTPException(status_code=409, detail="草稿引用的文件已经不存在。")
        path = Path(stored.stored_path).resolve()
        if not path.is_file() or stored.sha256 != expected or sha256_file(path) != expected:
            raise HTTPException(status_code=409, detail="草稿引用的文件内容已经变化。")
    run = create_run(
        db,
        RunCreate(
            skill_id=record.skill_id,
            message=record.message,
            parameters=parameters,
            files=files,
            idempotency_key=f"draft:{record.id}",
        ),
        user,
    )
    if run.state == "waiting_confirmation":
        run = confirm_run(db, run, user)
    record.state = "consumed"
    record.run_id = run.id
    record.updated_at = _now()
    db.flush()
    return run


def delete_task_draft(db: Session, draft_id: str, user: UserContext) -> None:
    record = _get_owned_draft(db, draft_id, user)
    if record.state == "consumed":
        raise HTTPException(status_code=409, detail="已创建任务的草稿不能删除。")
    traces = db.query(ModelTraceRecord).filter(
        ModelTraceRecord.task_draft_id == record.id,
        ModelTraceRecord.owner_id == user.user_id,
        ModelTraceRecord.department_id == user.department_id,
    )
    for trace in traces:
        trace.task_draft_id = None
    db.flush()
    db.delete(record)
    db.flush()
