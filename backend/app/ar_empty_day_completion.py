"""Recognize a completed v2 empty date without inventing a financial publication."""
from .ar_execution_contract import CONTRACT_VERSION


def is_completed_empty_day(context: dict, date: str) -> bool:
    execution = context.get("ar_execution") or {}
    proof = context.get("empty_day_evidence") or {}
    return (context.get("empty_day_skipped") is True
            and execution.get("schema_version") == CONTRACT_VERSION
            and execution.get("reconciliation_date") == date
            and execution.get("empty_day_skipped") is True
            and execution.get("publication") == "not_required_empty_day"
            and execution.get("completed") == ["inspect_materials", "classify_receipts"]
            and proof.get("schema") == "ar-empty-day-v1"
            and proof.get("date") == date and proof.get("empty") is True)
