"""Explicitly reviewed AR tools; each keeps its own materials and permissions."""
AR_SKILL_ID = "ar-hexiao-daily"
AR_LAB_SKILL_ID = "ar-hexiao-daily-lab"
AR_SKILL_IDS = frozenset({AR_SKILL_ID, AR_LAB_SKILL_ID})


def is_ar_skill(skill_id: str) -> bool:
    return skill_id in AR_SKILL_IDS
