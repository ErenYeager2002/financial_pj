"""Read a stopped Pi session's selected transcript without starting its container."""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath


MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
MAX_MESSAGES = 500


class HistoryError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _open_session_directory(root: Path, owner: str, session: str) -> int | None:
    """Pin every owner-controlled directory component with O_NOFOLLOW."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for name in ('owners', owner, 'home', '.pi', 'agent', 'sessions', 'platform', session):
            try:
                next_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=fd)
            except FileNotFoundError:
                return None
            os.close(fd)
            fd = next_fd
        result = fd
        fd = -1
        return result
    except OSError as exc:
        raise HistoryError(409, 'Invalid Pi session directory') from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _safe_file(directory_fd: int, name: str, max_bytes: int) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise HistoryError(409, 'Invalid Pi transcript file')
        if info.st_size > max_bytes:
            raise HistoryError(413, 'Pi transcript is too large for stopped-history view')
        chunks = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise HistoryError(413, 'Pi transcript is too large for stopped-history view')
        return b''.join(chunks)
    finally:
        os.close(fd)


def _selected_file(directory_fd: int, session: str) -> str | None:
    try:
        os.stat('active.json', dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        value = json.loads(_safe_file(directory_fd, 'active.json', 4096))
        virtual_parent = PurePosixPath('/home/agent/.pi/agent/sessions/platform') / session
        selected = value.get('file') if isinstance(value, dict) else None
        if not isinstance(selected, str):
            raise HistoryError(409, 'Invalid Pi active transcript pointer')
        virtual = PurePosixPath(selected)
        if virtual.parent != virtual_parent or virtual.suffix != '.jsonl' or virtual.name in {'', '.', '..'}:
            raise HistoryError(409, 'Invalid Pi active transcript pointer')
        return virtual.name
    files = [name for name in os.listdir(directory_fd) if name.endswith('.jsonl')]
    if len(files) > 1:
        raise HistoryError(409, 'Pi active transcript pointer is missing')
    return files[0] if files else None


def read_history(root: Path, owner: str, session: str) -> dict:
    directory_fd = _open_session_directory(root, owner, session)
    if directory_fd is None:
        return {'messages': [], 'truncated': False}
    try:
        selected = _selected_file(directory_fd, session)
        if selected is None:
            return {'messages': [], 'truncated': False}
        raw = _safe_file(directory_fd, selected, MAX_TRANSCRIPT_BYTES)
        lines = raw.split(b'\n')
        if lines[-1]:  # An interrupted final append is not a committed entry.
            lines.pop()
        entries: dict[str, dict] = {}
        leaf: str | None = None
        for line in lines:
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise HistoryError(409, 'Invalid Pi transcript entry')
            entry_id = item.get('id')
            if isinstance(entry_id, str):
                if entry_id in entries:
                    raise HistoryError(409, 'Duplicate Pi transcript entry')
                entries[entry_id] = item
                leaf = entry_id
        branch: list[dict] = []
        seen: set[str] = set()
        while leaf is not None:
            if leaf in seen or leaf not in entries:
                raise HistoryError(409, 'Broken Pi transcript branch')
            seen.add(leaf)
            item = entries[leaf]
            if item.get('type') == 'message' and isinstance(item.get('message'), dict):
                branch.append(item['message'])
            elif item.get('type') == 'custom_message' and item.get('display') is True:
                if not isinstance(item.get('customType'), str) or not isinstance(item.get('content'), (str, list)):
                    raise HistoryError(409, 'Invalid visible Pi extension message')
                created = datetime.fromisoformat(item.get('timestamp'))
                if created.tzinfo is None:
                    raise HistoryError(409, 'Invalid visible Pi extension timestamp')
                # Match the live Pi wire shape, without extension-private details.
                branch.append({'role': 'custom', 'customType': item['customType'],
                               'content': item['content'], 'display': True,
                               'timestamp': int(created.timestamp() * 1000)})
            parent = item.get('parentId')
            if parent is not None and not isinstance(parent, str):
                raise HistoryError(409, 'Invalid Pi transcript parent')
            leaf = parent
        branch.reverse()
        return {'messages': branch[-MAX_MESSAGES:], 'truncated': len(branch) > MAX_MESSAGES}
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HistoryError(409, 'Pi transcript could not be read') from exc
    finally:
        os.close(directory_fd)
