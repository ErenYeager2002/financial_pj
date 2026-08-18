from __future__ import annotations

from dataclasses import dataclass

from .redaction import sanitize_text


@dataclass(frozen=True)
class TaskErrorDetail:
    """A safe, user-facing description of one failed Skill step."""

    employee: str
    skill_id: str
    skill_name: str
    step_key: str
    step: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "employee": self.employee,
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "step_key": self.step_key,
            "step": self.step,
            "reason": self.reason,
        }

    def message(self) -> str:
        return (
            f"员工 {self.employee} 使用 Skill {self.skill_name} 时，"
            f"在步骤 {self.step} 出错：{self.reason}"
        )


def build_task_error(
    *,
    employee: str,
    skill_id: str,
    skill_name: str,
    step_key: str,
    step: str,
    reason: object,
) -> TaskErrorDetail:
    safe_employee = sanitize_text(employee or "未识别员工", max_length=128)
    safe_skill_id = sanitize_text(skill_id or "未识别 Skill", max_length=128)
    safe_skill_name = sanitize_text(skill_name or safe_skill_id, max_length=255)
    safe_step_key = sanitize_text(step_key or "unknown", max_length=128)
    safe_step = sanitize_text(step or safe_step_key, max_length=255)
    safe_reason = sanitize_text(
        str(reason),
        error=True,
        max_length=1200,
        hidden_message="技术错误详情已隐藏，请联系管理员查看审计记录。",
    )
    return TaskErrorDetail(
        employee=safe_employee,
        skill_id=safe_skill_id,
        skill_name=safe_skill_name,
        step_key=safe_step_key,
        step=safe_step,
        reason=safe_reason,
    )
