#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any


def _stable_row_identifier(row: dict[str, Any]) -> str:
    for key in ("rowid", "rowId", "_id", "id"):
        value = str(row.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    canonical = json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"content:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def summarize_dates(
    client: Any,
    business_dates: Iterable[str],
    *,
    worksheet_id: str,
    date_control_id: str,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for business_date in business_dates:
        rows, total = client.filter_rows_by_date(
            worksheet_id,
            date_control_id,
            business_date,
        )
        identifiers = sorted(_stable_row_identifier(row) for row in rows)
        digest = hashlib.sha256()
        for identifier in identifiers:
            digest.update(identifier.encode("utf-8"))
            digest.update(b"\n")
        results.append(
            {
                "business_date": business_date,
                "record_count": int(total),
                "fingerprint": digest.hexdigest(),
            }
        )
    return results


def _validated_dates(raw_dates: object) -> tuple[str, ...]:
    if not isinstance(raw_dates, list) or not 1 <= len(raw_dates) <= 31:
        raise ValueError("business_dates must contain between 1 and 31 dates")
    result: list[str] = []
    for raw_date in raw_dates:
        value = str(raw_date).strip()
        if date.fromisoformat(value).isoformat() != value or value in result:
            raise ValueError("business_dates must contain unique ISO dates")
        result.append(value)
    return tuple(result)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    vendor_dir = Path(
        os.environ.get("FINANCIAL_SKILL_DIR")
        or project_root / "skills" / "ar-hexiao-daily" / "vendor" / "scripts"
    ).resolve()
    sys.path.insert(0, str(vendor_dir))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    payload: dict[str, object] = {}
    password = ""
    client = None
    try:
        import fetch_zhiyun
        from secure_zhiyun_fetch import _edge_login

        parsed = json.loads(sys.stdin.read())
        if not isinstance(parsed, dict):
            raise TypeError("payload must be an object")
        payload = parsed
        account = str(payload.get("account") or "").strip()
        password = str(payload.get("password") or "")
        business_dates = _validated_dates(payload.get("business_dates"))
        if not account or not password:
            raise ValueError("credentials are required")

        base_url = str(
            os.environ.get("ZHIYUN_BASE") or fetch_zhiyun.BASE_DEFAULT
        ).strip()
        cookie, account_id = _edge_login(base_url, account, password)
        client = fetch_zhiyun.ZhiyunClient(
            base_url,
            cookie,
            account_id=account_id or "",
        )
        results = summarize_dates(
            client,
            business_dates,
            worksheet_id=fetch_zhiyun.WS_HUIKUAN,
            date_control_id=fetch_zhiyun.F_HK["hexiao_date"],
        )
        print(json.dumps({"results": results}, ensure_ascii=False))
        return 0
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        print("ERROR: 任务检查输入无效。", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - only allowlisted diagnostics cross the boundary
        from secure_zhiyun_fetch import LOGIN_FAILURE_MESSAGES

        phase = getattr(exc, "login_phase", "")
        reason = LOGIN_FAILURE_MESSAGES.get(phase)
        if not reason and isinstance(exc, ImportError):
            reason = "智云只读检查缺少运行依赖，请检查 Worker 的浏览器和 Python 环境。"
        print(f"ERROR: {reason or '智云只读任务检查失败，请检查取数服务及运行环境。'}", file=sys.stderr)
        return 1
    finally:
        password = ""
        payload.clear()
        if client is not None:
            try:
                client.session.close()
            except Exception:  # cleanup must not overwrite the probe outcome
                print("WARNING: 任务检查连接清理失败。", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
