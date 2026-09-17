from __future__ import annotations

FOUNDATION_SKILL_IDS = frozenset({"xlsx", "docx", "pdf", "pptx"})
SUPPORTING_SKILL_IDS = frozenset({"env-doctor", "task-clarifier"})
BUSINESS_EXECUTION_EXPERIENCE_IDS = frozenset(
    {
        "consolidated-statements",
        "ar-hexiao-daily",
        "ar-hexiao-daily-lab",
        "reconcile-bank",
        "receivables-merge-and-split",
        "labor-invoice-check",
        "withholding-report-rename",
        "pdf-compress",
        "compliance-spot-check",
        "dreame-ar-progress-diff",
        "dept-expense-alloc",
        "order-daily-summary",
        "project-detail-to-ledger",
    }
)


def validate_published_execution_experience(skill_id: str, status: str, interaction_mode: str = "form") -> None:
    if status != "published" or interaction_mode == "chat":
        return
    configured = (
        FOUNDATION_SKILL_IDS
        | SUPPORTING_SKILL_IDS
        | BUSINESS_EXECUTION_EXPERIENCE_IDS
    )
    if skill_id not in configured:
        raise ValueError(
            "published Skill 必须配置平台受控的专属执行体验，不能回退到通用表单"
        )
