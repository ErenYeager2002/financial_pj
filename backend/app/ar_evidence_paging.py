"""Bounded, lossless pages of already-redacted order evidence.

Every scalar has its original field path. Long strings are split with character
offsets; empty collections remain visible. Coverage refers to returned entries,
never to the number of summary records a model has listed.
"""
from __future__ import annotations

import gzip
import json
import threading
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Literal

from pydantic import BaseModel, Field

PAGING_VERSION = "ar-evidence-page-v2"
PAGE_BYTES = 96 * 1024
PAGE_ENTRIES = 500
STRING_CHARS = 1024
CACHE_BYTES = 64 * 1024 * 1024


class ArEvidenceEntry(BaseModel):
    path: list[str]
    kind: Literal["string", "number", "boolean", "null", "object", "array"]
    text: str
    char_offset: int = 0
    char_total: int = 0


class ArEvidenceDetail(BaseModel):
    record_id: str
    fingerprint: str
    total: int
    offset: int
    next_offset: int
    entries: list[ArEvidenceEntry] = Field(default_factory=list)


def _entries(value: Any, path: tuple[str, ...] = ()) -> Iterator[ArEvidenceEntry]:
    if isinstance(value, dict) and value:
        for key in sorted(value):
            yield from _entries(value[key], (*path, str(key)))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _entries(item, (*path, str(index)))
    elif isinstance(value, str):
        for offset in range(0, max(1, len(value)), STRING_CHARS):
            yield ArEvidenceEntry(path=list(path), kind="string",
                                  text=value[offset:offset + STRING_CHARS],
                                  char_offset=offset, char_total=len(value))
    else:
        kind = ("null" if value is None else "boolean" if isinstance(value, bool)
                else "object" if isinstance(value, dict) else "array" if isinstance(value, list)
                else "number")
        yield ArEvidenceEntry(path=list(path), kind=kind,
                              text=json.dumps(value, ensure_ascii=False, allow_nan=False))


@dataclass(frozen=True)
class EvidenceIndex:
    starts: tuple[int, ...]
    pages: tuple[bytes, ...]
    total: int
    size: int


_indexes: OrderedDict[str, EvidenceIndex] = OrderedDict()
_index_bytes = 0
_index_lock = threading.Lock()


def _build_index(safe: dict[str, Any]) -> EvidenceIndex:
    pages = []
    starts = []
    selected: list[str] = []
    size = 0
    total = 0

    def finish_page() -> None:
        starts.append(total - len(selected))
        pages.append(gzip.compress(("[" + ",".join(selected) + "]").encode("utf-8"), mtime=0))

    for entry in _entries(safe):
        encoded = entry.model_dump_json()
        entry_size = len(encoded.encode("utf-8")) + 1
        if entry_size > PAGE_BYTES:
            raise ValueError("evidence field path exceeds page boundary")
        if selected and (size + entry_size > PAGE_BYTES or len(selected) >= PAGE_ENTRIES):
            finish_page()
            selected = []
            size = 0
        selected.append(encoded)
        size += entry_size
        total += 1
    if selected:
        finish_page()
    return EvidenceIndex(tuple(starts), tuple(pages), total,
                         sum(len(page) for page in pages) + len(pages) * 128)


def detail_page(record_id: str, safe_factory: Callable[[], dict[str, Any]], offset: int,
                fingerprint: str) -> ArEvidenceDetail:
    """Cache only redacted pages keyed by verified input hashes and record identity.

    The size-bounded cache is an optimization, never an execution fact. A restart
    rebuilds it from the same fixed sources; no cached page is accepted from disk.
    """
    global _index_bytes
    with _index_lock:
        index = _indexes.get(fingerprint)
        if index is not None:
            _indexes.move_to_end(fingerprint)
    if index is None:
        index = _build_index(safe_factory())
        with _index_lock:
            if fingerprint not in _indexes and index.size <= CACHE_BYTES:
                while _indexes and _index_bytes + index.size > CACHE_BYTES:
                    _, removed = _indexes.popitem(last=False)
                    _index_bytes -= removed.size
                _indexes[fingerprint] = index
                _index_bytes += index.size
    offset = min(offset, index.total)
    entries = []
    if offset < index.total:
        page_number = bisect_right(index.starts, offset) - 1
        rows = json.loads(gzip.decompress(index.pages[page_number]))
        entries = [ArEvidenceEntry.model_validate(row) for row in rows[offset - index.starts[page_number]:]]
    return ArEvidenceDetail(record_id=record_id, fingerprint=fingerprint, total=index.total,
                            offset=offset, next_offset=offset + len(entries), entries=entries)


def merge_read_ranges(ranges: list[list[int]], start: int, end: int) -> list[list[int]]:
    merged: list[list[int]] = []
    for left, right in sorted([*ranges, [start, end]]):
        if left >= right:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])
    return merged
