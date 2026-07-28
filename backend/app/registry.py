from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .settings import settings


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
    adapter: Literal["python", "rpa", "http"]
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


class RuntimeSpec(BaseModel):
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    memory_mb: int = Field(default=1024, ge=128)
    concurrency_limit: int = Field(default=1, ge=1)
    network_access: bool = False
    network_allowlist: list[str] = Field(default_factory=list)


class RiskSpec(BaseModel):
    level: Literal["read_only", "write", "external_action"] = "read_only"
    requires_confirmation: bool = False


class PermissionSpec(BaseModel):
    run: str = "finance_user"
    manage: str = "skill_admin"


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
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    risk: RiskSpec = Field(default_factory=RiskSpec)
    permissions: PermissionSpec = Field(default_factory=PermissionSpec)


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
                    manifest = SkillManifest.model_validate(payload)
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
