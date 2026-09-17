from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .network_policy import validate_runtime_network_policy
from .settings import settings
from .skill_execution_experiences import validate_published_execution_experience

EMPLOYEE_LABEL_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(?:https?://|www\.)"),
    re.compile(r"(?i)(?:[A-Za-z0-9-]+\.)+(?:com|cn|net|org|io|local)(?:[/:]|$)"),
    re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?!\d)"),
    re.compile(r"[\\/]"),
    re.compile(
        r"(?i)(?:password|passwd|api[_ -]?key|secret|token|account|账号|账户|密码|密钥)"
    ),
    re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{7,40}(?![0-9a-f])"),
    re.compile(r"\S+@\S+\.\S+"),
)


class FileInputSpec(BaseModel):
    role: str
    name: str
    description: str = ""
    required: bool = True
    multiple: bool = False
    min_files: int = Field(default=1, ge=0)
    extensions: list[str] = Field(default_factory=list)
    max_size_mb: int | None = None


class HandlerSpec(BaseModel):
    adapter: Literal["python", "rpa", "http", "workflow"]
    entrypoint: str | None = None
    endpoint: str | None = None
    worker_pool: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> HandlerSpec:
        if self.adapter in {"python", "rpa"} and not self.entrypoint:
            raise ValueError("python/rpa handler 必须配置 entrypoint")
        if self.adapter == "http" and not self.endpoint:
            raise ValueError("http handler 必须配置 endpoint")
        return self


class ExecutionModeSpec(BaseModel):
    adapter: Literal["workflow", "pi_harness"]
    worker_pool: str = Field(min_length=1, max_length=64)
    instructions: str | None = None
    tools: str | None = None

    @model_validator(mode="after")
    def validate_pi_harness_files(self) -> ExecutionModeSpec:
        if self.adapter == "pi_harness" and (not self.instructions or not self.tools):
            raise ValueError("pi_harness 执行模式必须声明 instructions 和 tools")
        return self


class ExecutionSpec(BaseModel):
    default_mode: Literal["workflow", "pi_harness"] = "workflow"
    modes: dict[Literal["workflow", "pi_harness"], ExecutionModeSpec]

    @model_validator(mode="after")
    def validate_modes(self) -> ExecutionSpec:
        if self.default_mode not in self.modes:
            raise ValueError("execution.default_mode 必须出现在 execution.modes 中")
        for name, mode in self.modes.items():
            if name != mode.adapter:
                raise ValueError(f"执行模式 {name} 的 adapter 必须与模式名一致")
        return self


class RuntimeSpec(BaseModel):
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    memory_mb: int = Field(default=1024, ge=128)
    concurrency_limit: int = Field(default=1, ge=1)
    network_access: bool = False
    network_allowlist: list[str] = Field(default_factory=list)
    network_targets: list[str] = Field(default_factory=list)


class RiskSpec(BaseModel):
    level: Literal["read_only", "write", "external_action"] = "read_only"
    requires_confirmation: bool = False
    requires_change_review: bool = False
    requires_approval: bool = False
    modifies_uploaded_files: bool = False


class ExternalDataSourceSpec(BaseModel):
    system: str = Field(min_length=1, max_length=80)
    access: Literal[
        "uploaded_export",
        "direct_read",
        "browser_rpa",
        "repository_sync",
    ]
    required: bool = True


class SkillOperationalProfileSpec(BaseModel):
    execution_kind: Literal[
        "offline_file",
        "guided_workflow",
        "browser_rpa",
        "agent_guidance",
        "document_agent",
    ]
    external_sources: list[ExternalDataSourceSpec] = Field(
        default_factory=list,
        max_length=10,
    )
    employee_labels: list[str] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_labels(self) -> SkillOperationalProfileSpec:
        labels = [label.strip() for label in self.employee_labels]
        if any(not label or len(label) > 20 for label in labels):
            raise ValueError("employee_labels 每项必须为 1 至 20 个字符")
        if len(labels) != len(set(labels)):
            raise ValueError("employee_labels 不能重复")
        if any(
            pattern.search(label)
            for label in labels
            for pattern in EMPLOYEE_LABEL_SENSITIVE_PATTERNS
        ):
            raise ValueError("employee_labels 不能包含地址、账号、密钥、路径或源码版本")
        self.employee_labels = labels
        return self


def _legacy_operational_profile() -> SkillOperationalProfileSpec:
    return SkillOperationalProfileSpec(
        execution_kind="offline_file",
        external_sources=[],
        employee_labels=["历史运行快照", "按原配置执行"],
    )


def validate_declared_operational_profile(payload: Any) -> None:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("operational_profile"), dict
    ):
        raise ValueError("Skill 必须显式声明 operational_profile")


class SkillUiSpec(BaseModel):
    employee_name: str = Field(min_length=1, max_length=128)
    short_description: str = Field(min_length=1, max_length=300)
    categories: list[str] = Field(min_length=1, max_length=5)
    estimated_minutes: int = Field(ge=1, le=1440)
    output_summary: str = Field(min_length=1, max_length=300)
    action_label: str = Field(min_length=1, max_length=40)
    popular: bool = False


class SafetyConstraintSpec(BaseModel):
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_range(self) -> SafetyConstraintSpec:
        if self.minimum is None and self.maximum is None:
            raise ValueError("安全约束至少需要 minimum 或 maximum")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("安全约束 minimum 不能大于 maximum")
        return self


class ProgressStageSpec(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)


class ResultMetricSpec(BaseModel):
    key: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$")
    label: str = Field(min_length=1, max_length=80)


class ResultPresentationSpec(BaseModel):
    metrics: list[ResultMetricSpec] = Field(default_factory=list, max_length=20)


class PermissionSpec(BaseModel):
    run: str = "finance_user"
    manage: str = "skill_admin"


class ConversationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["form", "chat"] = "form"
    capabilities: list[Literal["prepare_task_draft", "query_task_status"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capabilities(self):
        if self.mode == "chat" and set(self.capabilities) != {"prepare_task_draft", "query_task_status"}:
            raise ValueError("当前对话 Skill 必须声明 prepare_task_draft 和 query_task_status 两项能力")
        return self


def validate_conversation_files(manifest, directory: Path) -> None:
    if manifest.conversation.mode != "chat":
        return
    base = directory.resolve()
    instructions = (base / "SKILL.md").resolve()
    if not instructions.is_relative_to(base) or not instructions.is_file():
        raise ValueError("对话 Skill 必须包含包内 SKILL.md")
    if not 0 < instructions.stat().st_size <= 131072:
        raise ValueError("SKILL.md 必须为非空文本且不超过 128 KiB")
    if not instructions.read_text(encoding="utf-8-sig").strip():
        raise ValueError("SKILL.md 不能为空")


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    id: str
    name: str
    version: str
    status: Literal["draft", "published", "disabled"] = "draft"
    category: str = "其他"
    description: str
    tags: list[str] = Field(default_factory=list)
    file_inputs: list[FileInputSpec] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    handler: HandlerSpec
    execution: ExecutionSpec | None = None
    catalog_module: Literal["tools", "installed_skills"] = "tools"
    conversation: ConversationSpec = Field(default_factory=ConversationSpec)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    risk: RiskSpec = Field(default_factory=RiskSpec)
    operational_profile: SkillOperationalProfileSpec = Field(
        default_factory=_legacy_operational_profile
    )
    permissions: PermissionSpec = Field(default_factory=PermissionSpec)
    ui: SkillUiSpec | None = None
    safety_constraints: dict[str, SafetyConstraintSpec] = Field(default_factory=dict)
    progress_stages: list[ProgressStageSpec] = Field(default_factory=list)
    result_presentation: ResultPresentationSpec = Field(
        default_factory=ResultPresentationSpec
    )

    @model_validator(mode="after")
    def validate_employee_metadata(self) -> SkillManifest:
        if self.conversation.mode == "chat":
            if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", self.id) or len(self.id) > 80:
                raise ValueError("对话 Skill id 必须为不超过 80 字符的小写字母数字和连字符")
            if self.handler.adapter != "python" or self.risk.level != "read_only" or self.risk.modifies_uploaded_files or self.runtime.network_access:
                raise ValueError("当前标准对话仅支持离线、只读、不改原件的 Python Skill；其他能力尚未适配")
            if len({f.role for f in self.file_inputs}) != len(self.file_inputs):
                raise ValueError("输入文件 role 不能重复")
        if self.ui and len(set(self.ui.categories)) != len(self.ui.categories):
            raise ValueError("ui.categories 不能重复")
        stage_keys = [item.key for item in self.progress_stages]
        if len(stage_keys) != len(set(stage_keys)):
            raise ValueError("progress_stages.key 不能重复")
        metric_keys = [item.key for item in self.result_presentation.metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("result_presentation.metrics.key 不能重复")
        direct_access = {"direct_read", "browser_rpa", "repository_sync"}
        if any(
            source.access in direct_access
            for source in self.operational_profile.external_sources
        ) and not self.runtime.network_access:
            raise ValueError("外部直连取数必须启用 runtime.network_access")
        if (
            self.operational_profile.execution_kind == "guided_workflow"
            and self.handler.adapter != "workflow"
        ):
            raise ValueError("guided_workflow 必须使用 workflow handler")
        if self.execution and "workflow" in self.execution.modes:
            if self.handler.adapter != "workflow":
                raise ValueError("workflow 执行模式必须保留 workflow handler")
        if (
            self.operational_profile.execution_kind == "browser_rpa"
            and self.handler.adapter != "rpa"
        ):
            raise ValueError("browser_rpa 必须使用 rpa handler")
        if (
            self.handler.adapter == "rpa"
            and self.operational_profile.execution_kind != "browser_rpa"
        ):
            raise ValueError("rpa handler 必须声明 browser_rpa 运行方式")
        properties = self.input_schema.get("properties", {})
        for name, constraint in self.safety_constraints.items():
            schema = properties.get(name)
            if not isinstance(schema, dict):
                raise ValueError(f"safety_constraints 引用了未知参数：{name}")
            schema_min = schema.get("minimum")
            schema_max = schema.get("maximum")
            if (
                constraint.minimum is not None
                and schema_min is not None
                and constraint.minimum < schema_min
            ):
                raise ValueError(f"{name} 安全下限不能小于 input_schema.minimum")
            if (
                constraint.maximum is not None
                and schema_max is not None
                and constraint.maximum > schema_max
            ):
                raise ValueError(f"{name} 安全上限不能大于 input_schema.maximum")
        return self


class RegisteredSkill(BaseModel):
    manifest: SkillManifest
    directory: Path
    manifest_path: Path
    skill_hash: str
    commit_sha: str = ""
    source: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def public_dict(self, include_schema: bool = True) -> dict[str, Any]:
        data = self.manifest.model_dump()
        if not include_schema:
            data.pop("input_schema", None)
            data.pop("output_schema", None)
        data.update(
            {
                "skill_hash": self.skill_hash,
                "commit_sha": self.commit_sha,
                "source": self.source,
            }
        )
        return data

    def employee_dict(self, include_schema: bool = True) -> dict[str, Any]:
        """Return business-facing fields only; never expose runtime internals."""
        ui = self.manifest.ui
        if ui is None:
            raise ValueError(f"Skill {self.manifest.id} 缺少员工展示配置")
        data: dict[str, Any] = {
            "id": self.manifest.id,
            "name": ui.employee_name,
            "version": self.manifest.version,
            "status": self.manifest.status,
            "description": ui.short_description,
            "categories": ui.categories,
            "estimated_minutes": ui.estimated_minutes,
            "output_summary": ui.output_summary,
            "action_label": ui.action_label,
            "popular": ui.popular,
            "tags": self.manifest.tags,
            "operation_labels": self.manifest.operational_profile.employee_labels,
            "file_inputs": [item.model_dump() for item in self.manifest.file_inputs],
            "risk": {
                "level": self.manifest.risk.level,
                "requires_confirmation": self.manifest.risk.requires_confirmation,
                "requires_approval": self.manifest.risk.requires_approval,
                "modifies_uploaded_files": self.manifest.risk.modifies_uploaded_files,
            },
            "catalog_module": self.manifest.catalog_module,
            "interaction_mode": self.manifest.conversation.mode,
            "execution_mode": (
                "guided_workflow"
                if self.manifest.handler.adapter == "workflow"
                else "standard"
            ),
            "execution_modes": (
                list(self.manifest.execution.modes)
                if self.manifest.execution
                else ["workflow"]
                if self.manifest.handler.adapter == "workflow"
                else []
            ),
            "default_execution_mode": (
                self.manifest.execution.default_mode
                if self.manifest.execution
                else "workflow"
                if self.manifest.handler.adapter == "workflow"
                else None
            ),
            "progress_stages": [
                item.model_dump() for item in self.manifest.progress_stages
            ],
            "result_presentation": self.manifest.result_presentation.model_dump(),
        }
        if include_schema:
            data["input_schema"] = self.manifest.input_schema
        return data


def _git_commit(path: Path) -> str:
    current = path
    while current != current.parent:
        if (current / ".git").exists():
            try:
                return subprocess.check_output(
                    ["git", "-C", str(current), "rev-parse", "HEAD"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).strip()
            except (OSError, subprocess.SubprocessError):
                return ""
        current = current.parent
    return ""


HASH_IGNORES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "工作区",
    "output",
    "node_modules",
}


def _hash_skill(manifest_path: Path, manifest: SkillManifest) -> str:
    digest = hashlib.sha256()
    skill_dir = manifest_path.parent.resolve()
    for path in sorted(skill_dir.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or any(part in HASH_IGNORES for part in path.parts):
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(skill_dir):
            raise ValueError(f"Skill 文件超出目录边界：{path}")
        digest.update(path.relative_to(skill_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, RegisteredSkill] = {}
        self.errors: list[dict[str, str]] = []

    @property
    def roots(self) -> list[tuple[Path, str]]:
        roots = [(settings.skill_dir, "platform")]
        if settings.external_skill_dir:
            roots.append((settings.external_skill_dir, "external"))
        return roots

    def refresh(self) -> None:
        skills: dict[str, RegisteredSkill] = {}
        errors: list[dict[str, str]] = []
        for root, source in self.roots:
            if not root.exists():
                continue
            for manifest_path in sorted(root.glob("*/tool.yaml")):
                try:
                    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                    validate_declared_operational_profile(payload)
                    manifest = SkillManifest.model_validate(payload)
                    validate_conversation_files(manifest, manifest_path.parent)
                    if manifest.execution:
                        skill_dir = manifest_path.parent.resolve()
                        for mode in manifest.execution.modes.values():
                            for relative in (mode.instructions, mode.tools):
                                if not relative:
                                    continue
                                declared = (skill_dir / relative).resolve()
                                if not declared.is_relative_to(skill_dir) or not declared.is_file():
                                    raise ValueError(f"执行模式引用的 Skill 文件不存在：{relative}")
                    if manifest.status == "published" and manifest.ui is None:
                        raise ValueError("published Skill 必须配置 ui")
                    if manifest.status == "published":
                        validate_published_execution_experience(
                            manifest.id, manifest.status, manifest.conversation.mode
                        )
                        validate_runtime_network_policy(manifest.runtime)
                    registered = RegisteredSkill(
                        manifest=manifest,
                        directory=manifest_path.parent.resolve(),
                        manifest_path=manifest_path.resolve(),
                        skill_hash=_hash_skill(manifest_path, manifest),
                        commit_sha=_git_commit(manifest_path.parent),
                        source=source,
                    )
                    existing = skills.get(manifest.id)
                    if existing and source == "external":
                        continue
                    skills[manifest.id] = registered
                except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
                    errors.append({"path": str(manifest_path), "error": str(exc)})
        self._skills = skills
        self.errors = errors

    def list(self, include_disabled: bool = False) -> list[RegisteredSkill]:
        skills = list(self._skills.values())
        if not include_disabled:
            skills = [item for item in skills if item.manifest.status == "published"]
        return sorted(skills, key=lambda item: (item.manifest.category, item.manifest.name))

    def get(self, skill_id: str, include_unpublished: bool = False) -> RegisteredSkill | None:
        skill = self._skills.get(skill_id)
        if not skill:
            return None
        if not include_unpublished and skill.manifest.status != "published":
            return None
        return skill

    def snapshot(self, skill: RegisteredSkill) -> str:
        return json.dumps(
            skill.public_dict(include_schema=True),
            ensure_ascii=False,
            sort_keys=True,
        )


registry = SkillRegistry()
