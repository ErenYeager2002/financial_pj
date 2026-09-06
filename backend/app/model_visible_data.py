from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VISIBLE_REDACTION = "[认证信息已过滤]"
UNSAFE_CONTENT = "[内容无法安全解析，已隐藏]"
OVERSIZE_CONTENT = "[文件超过受控读取大小，内容已隐藏]"
MAX_MODEL_VISIBLE_BYTES = 1024 * 1024

_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "secret",
        "secret_key",
        "session_cookie",
        "token",
    }
)
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(?<![\w-])(?P<prefix>[\"']?(?:[A-Za-z0-9][A-Za-z0-9\s_-]*?[\s_-])?"
    r"(?:access[\s_-]*token|api[\s_-]*key|apikey|authorization|client[\s_-]*secret|"
    r"cookie|credential(?:s)?|password|passwd|private[\s_-]*key|refresh[\s_-]*token|"
    r"secret(?:[\s_-]*key)?|session[\s_-]*cookie|token)[\"']?[ \t]*[:=][ \t]*)"
    r"(?P<value>(?:\bbearer\s+[A-Za-z0-9._~+/=-]+|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;\]}]+)?"
    r"(?:[ \t]+[^\r\n]*)?(?:\r?\n[ \t]+[^\r\n]*)*)",
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def _normalized_key(key: object) -> str:
    value = str(key).strip().strip("\"'`").casefold()
    return re.sub(r"[\s\-_]+", "_", value)


def _is_secret_key(key: object) -> bool:
    normalized = _normalized_key(key)
    return normalized in _SECRET_KEYS or normalized.endswith(
        ("_api_key", "_cookie", "_credential", "_password", "_secret", "_token")
    )


def visible_value(value: Any) -> Any:
    """Redact structured values while retaining ordinary business fields."""
    if isinstance(value, dict):
        return {
            str(key): VISIBLE_REDACTION if _is_secret_key(key) else visible_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [visible_value(item) for item in value]
    if isinstance(value, tuple):
        return [visible_value(item) for item in value]
    if isinstance(value, str):
        return _plain_text_visible(value)
    return value


def _plain_text_visible(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{VISIBLE_REDACTION}"

    redacted = _SECRET_KEY_PATTERN.sub(replace, value)
    return _BEARER_PATTERN.sub(VISIBLE_REDACTION, redacted)


def visible_text(value: str, *, format_hint: str = "") -> str:
    """Return model-safe text after structure-aware redaction.

    Structured input is normalized only after it has been parsed. A malformed
    JSON/YAML document is hidden rather than returned as raw text.
    """
    text = value if isinstance(value, str) else str(value)
    suffix = format_hint.casefold().lstrip(".")
    stripped = text.lstrip()
    looks_like_json = stripped.startswith(("{", "["))
    if suffix == "json":
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return UNSAFE_CONTENT
        else:
            return json.dumps(visible_value(parsed), ensure_ascii=False, separators=(",", ":"))
    if looks_like_json:
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            # A Markdown link or a bracketed business note is ordinary text;
            # it still goes through the plain-text secret filter below.
            pass
        else:
            return json.dumps(visible_value(parsed), ensure_ascii=False, separators=(",", ":"))
    if suffix in {"yaml", "yml"}:
        try:
            parsed_yaml = yaml.safe_load(text)
        except yaml.YAMLError:
            return UNSAFE_CONTENT
        if isinstance(parsed_yaml, (dict, list, tuple)):
            return yaml.safe_dump(
                visible_value(parsed_yaml),
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ).rstrip("\n")
    return _plain_text_visible(text)


def _utf8_page(data: bytes, offset: int, limit: int) -> tuple[str, int, int]:
    start = min(max(offset, 0), len(data))
    while start < len(data) and data[start] & 0xC0 == 0x80:
        start += 1
    end = min(start + max(limit, 1), len(data))
    while end > start and end < len(data) and data[end] & 0xC0 == 0x80:
        end -= 1
    if end == start and start < len(data):
        end = start + 1
        while end < len(data) and data[end] & 0xC0 == 0x80:
            end += 1
    return data[start:end].decode("utf-8"), start, end


@dataclass(frozen=True)
class SafeTextPage:
    content: str
    total_bytes: int
    offset: int
    limit: int
    next_offset: int
    available: bool = True


def read_safe_text_page(
    path: Path,
    *,
    offset: int,
    limit: int,
    format_hint: str = "",
) -> SafeTextPage:
    """Read a bounded file, redact it, then page the safe UTF-8 content."""
    try:
        size = path.stat().st_size
        if size > MAX_MODEL_VISIBLE_BYTES:
            return SafeTextPage(OVERSIZE_CONTENT, 0, 0, limit, 0, available=False)
        with path.open("rb") as handle:
            raw = handle.read(MAX_MODEL_VISIBLE_BYTES + 1)
    except (OSError, ValueError):
        return SafeTextPage(UNSAFE_CONTENT, 0, 0, limit, 0, available=False)
    if len(raw) > MAX_MODEL_VISIBLE_BYTES:
        return SafeTextPage(OVERSIZE_CONTENT, 0, 0, limit, 0, available=False)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return SafeTextPage(UNSAFE_CONTENT, 0, 0, limit, 0, available=False)
    safe = visible_text(text, format_hint=format_hint)
    data = safe.encode("utf-8")
    content, actual_offset, next_offset = _utf8_page(data, offset, limit)
    return SafeTextPage(
        content=content,
        total_bytes=len(data),
        offset=actual_offset,
        limit=limit,
        next_offset=next_offset,
    )
