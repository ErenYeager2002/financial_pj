from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "cookie",
    "config",
    "path",
    "prompt",
    "header",
    "environment",
)
_ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/][^\r\n\t]+|(?<![:\w])/(?:[^/\s]+/)+[^/\s]*)"
)
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|cookie)\s*[:=]\s*[^\s,;]+"
)
_STACK_TRACE = re.compile(
    r"(?i)(traceback \(most recent call last\)|\bfile \".+\", line \d+|\bat .+\(.+:\d+:\d+\))"
)
MAX_SUMMARY_DEPTH = 6
MAX_SUMMARY_ITEMS = 50
MAX_TEXT_LENGTH = 500


def sanitize_text(
    value: str,
    *,
    error: bool = False,
    max_length: int = MAX_TEXT_LENGTH,
    hidden_message: str = "任务执行失败，技术详情已隐藏。",
) -> str:
    if error and _STACK_TRACE.search(value):
        return hidden_message
    sanitized = _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=<已隐藏>", value)
    sanitized = _ABSOLUTE_PATH.sub("<已隐藏路径>", sanitized)
    return sanitized[:max_length]


def sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_SUMMARY_DEPTH:
        return "<内容过深，已省略>"
    if isinstance(value, dict):
        return {
            str(key)[:80]: sanitize_value(item, depth=depth + 1)
            for key, item in list(value.items())[:MAX_SUMMARY_ITEMS]
            if not any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, list):
        return [
            sanitize_value(item, depth=depth + 1)
            for item in value[:MAX_SUMMARY_ITEMS]
        ]
    if isinstance(value, str):
        return sanitize_text(
            value,
            error=True,
            hidden_message="步骤执行失败，技术详情已隐藏。",
        )
    if isinstance(value, (int, float, bool, type(None))):
        return value
    return str(value)[:MAX_TEXT_LENGTH]
