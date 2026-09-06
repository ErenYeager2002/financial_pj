from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .redaction import sanitize_text


def business_error_reason(reason: object) -> str:
    """Recognize known input failures without exposing subprocess traceback text."""
    value = str(reason)
    # Only inspect the terminal exception line, never a source-code/stack frame.
    terminal = value.strip().splitlines()[-1] if value.strip() else ""
    match = re.fullmatch(
        r"(?:ValueError: )?(银行流水|财务总账|总账)(没有找到日期列|没有找到金额列|没有表头)(?:[，。].*)?",
        terminal,
    )
    if match:
        label, problem = match.groups()
        instructions = {
            "没有找到日期列": "请补充日期列，并使用该 Skill 支持的日期表头。",
            "没有找到金额列": "请补充金额列，并使用该 Skill 支持的金额表头。",
            "没有表头": "请在第一行填写表头后重新上传。",
        }
        return f"{label}{problem}。{instructions[problem]}"
    return sanitize_text(
        value, error=True, max_length=1200,
        hidden_message="技术错误详情已隐藏，请联系管理员查看审计记录。",
    )


@dataclass(frozen=True)
class TaskErrorDetail:
    """A safe, user-facing description of one failed Skill step."""

    employee: str
    skill_id: str
    skill_name: str
    step_key: str
    step: str
    reason: str
    error_code: str = "WORKFLOW_STEP_FAILED"
    category: str = "unknown"
    write_status: str = "unknown"
    published_material_version: str = ""
    recovery_allowed: bool | None = None
    failed_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "employee": self.employee,
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "step_key": self.step_key,
            "step": self.step,
            "reason": self.reason,
            "error_code": self.error_code,
            "category": self.category,
            "write_status": self.write_status,
            "published_material_version": self.published_material_version,
            "recovery_allowed": self.recovery_allowed,
            "failed_at": self.failed_at,
        }

    def message(self) -> str:
        return (
            f"员工 {self.employee} 使用 Skill {self.skill_name} 时，"
            f"在步骤 {self.step} 出错：{self.reason}"
        )


def classify_task_error(reason: object, *, step_key: str = "", stage: str = "") -> tuple[str, str]:
    """Map an internal failure to a small, safe set of user-facing categories."""
    value = str(reason).casefold()
    step = f"{step_key} {stage}".casefold()
    if "权限" in value or "permission" in value or "账号" in value and "停用" in value:
        return "WORKFLOW_PERMISSION_RECHECK_FAILED", "permission"
    if "版本" in value or "material" in value or "fingerprint" in value:
        return "WORKFLOW_MATERIAL_VERSION_CONFLICT", "version_conflict"
    if "智云" in value or "credential" in value or "凭据" in value or "network" in value:
        return "WORKFLOW_FETCH_UNAVAILABLE", "network_credentials"
    if any(word in value for word in ("输入", "文件", "材料", "hash", "表头", "日期列", "金额列")):
        return "WORKFLOW_INPUT_MATERIAL_INVALID", "input_material"
    if "规则" in value or "匹配" in value or "业务" in value:
        return "WORKFLOW_BUSINESS_RULE_FAILED", "business_rule"
    if "lease" in value or "worker" in value or "agent" in value or "中断" in value:
        return "WORKFLOW_WORKER_INTERRUPTED", "worker_agent_interrupted"
    if "write" in step or "写入" in value:
        return "WORKFLOW_WRITE_FAILED", "business_rule"
    return "WORKFLOW_STEP_FAILED", "unknown"


def build_task_error(
    *,
    employee: str,
    skill_id: str,
    skill_name: str,
    step_key: str,
    step: str,
    reason: object,
    error_code: str = "WORKFLOW_STEP_FAILED",
    category: str = "unknown",
    write_status: str = "unknown",
    published_material_version: object = "",
    recovery_allowed: bool | None = None,
    failed_at: datetime | None = None,
) -> TaskErrorDetail:
    safe_employee = sanitize_text(employee or "未识别员工", max_length=128)
    safe_skill_id = sanitize_text(skill_id or "未识别 Skill", max_length=128)
    safe_skill_name = sanitize_text(skill_name or safe_skill_id, max_length=255)
    safe_step_key = sanitize_text(step_key or "unknown", max_length=128)
    safe_step = sanitize_text(step or safe_step_key, max_length=255)
    safe_reason = business_error_reason(reason)
    if error_code == "WORKFLOW_STEP_FAILED" and category == "unknown":
        error_code, category = classify_task_error(safe_reason, step_key=step_key)
    return TaskErrorDetail(
        employee=safe_employee,
        skill_id=safe_skill_id,
        skill_name=safe_skill_name,
        step_key=safe_step_key,
        step=safe_step,
        reason=safe_reason,
        error_code=sanitize_text(error_code or "WORKFLOW_STEP_FAILED", max_length=64),
        category=sanitize_text(category or "unknown", max_length=64),
        write_status=sanitize_text(write_status or "unknown", max_length=64),
        published_material_version=sanitize_text(
            str(published_material_version or ""), max_length=64
        ),
        recovery_allowed=recovery_allowed,
        failed_at=(failed_at or datetime.now(UTC)).isoformat(),
    )
