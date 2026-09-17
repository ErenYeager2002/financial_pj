"""Read and reconcile dated Zhiyun export snapshots."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
import common
import datetime as dt
import json
import re
import writeoff_duplicate_audit as WDA
from classification_amounts import _prepare_parent_totals
from classification_contract import CoverageError, InputError, TOL


HUIKUAN_NAMES = {
    "ar": ["回款记录ID", "回款记录编号"],
    "currency": ["原币币种", "币种"],
    "arrival_date": ["到账日期", "回款日期"],
    "amount_orig": ["到账金额/原币", "到账金额原币"],
    "amount_local": ["到账金额/本币", "到账金额本币"],
    "total_amount_orig": ["总到账金额/原币", "总到账金额原币", "总到账金额"],
    "total_amount_local": ["总到账金额/本币", "总到账金额本币"],
    "fee": ["手续费/原币", "手续费"],
    "fee_local": ["手续费/本币", "手续费本币"],
    "tax": ["税费/原币", "税费"],
    "tax_local": ["税费/本币", "税费本币"],
    "other_fee": ["其他费用/原币", "其他费用"],
    "other_fee_local": ["其他费用/本币", "其他费用本币"],
    "huikuan_type": ["回款类型"],
    "status": ["核销状态"],
    "customer": ["开票客户", "客户名称", "客户"],
    "hexiao_date": ["核销日期"],
}

def _sheet_rows(path: Path) -> Tuple[List[str], List[list]]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    headers = [str(c).strip() if c is not None else "" for c in rows[0]]
    body = [list(r) for r in rows[1:] if any(x is not None and str(x).strip() for x in r)]
    return headers, body

def _col(headers: Sequence[str], role: str, key: str, aliases: dict) -> Optional[int]:
    cands = (aliases.get(role) or {}).get(key, [key])
    return common.fuzzy_find_col(headers, cands)

def _need(headers: Sequence[str], role: str, keys: Sequence[str], aliases: dict) -> Dict[str, int]:
    out = {}
    missing = []
    for k in keys:
        i = _col(headers, role, k, aliases)
        if i is None:
            missing.append(k)
        else:
            out[k] = i
    if missing:
        raise InputError(
            f"「{role}」缺列 {missing}。实际表头：{[h for h in headers if h]}"
        )
    return out

def _get(vals: list, idx: Optional[int]) -> Any:
    if idx is None or idx >= len(vals):
        return None
    return vals[idx]

EXPORT_DATE_RE = re.compile(r"(20\d{6})")

def _export_date(path: Path) -> Optional[dt.date]:
    """从导出文件名提取 YYYYMMDD；老金标文件无日期时返回 None。"""
    m = EXPORT_DATE_RE.search(path.stem)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None

def _role_files(directory: Path, *keys: str) -> List[Path]:
    return [
        p for p in sorted(directory.glob("*.xlsx"))
        if not p.name.startswith("~$") and any(k in p.name for k in keys)
    ]

def _base_export(
    files: List[Path], role: str, target_date: Optional[dt.date], required: bool = True
) -> Optional[Path]:
    """
    选当天主快照。目录里有多天文件时禁止再拿“排序第一份”冒充目标日。
    无日期文件只用于兼容单文件金标夹具。
    """
    if target_date is not None:
        exact = [p for p in files if _export_date(p) == target_date]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise InputError(f"「{role}」{target_date} 有多份主快照：{[p.name for p in exact]}")
        if len(files) == 1 and _export_date(files[0]) is None:
            return files[0]
        if required:
            raise InputError(f"没有「{role}」{target_date.strftime('%Y%m%d')} 的主快照")
        return None
    if len(files) == 1:
        return files[0]
    if not files:
        if required:
            raise InputError(f"01_智云导出/ 里没有「{role}」表")
        return None
    raise InputError(
        f"01_智云导出/ 里有多天「{role}」文件，必须用 --hexiao-date 指定核销日："
        f"{[p.name for p in files]}"
    )

def _eligible_snapshots(files: List[Path], target_date: Optional[dt.date], base: Optional[Path]) -> List[Path]:
    """补跑时可从更晚核销日文件还原历史子明细；无日期金标仍只读主文件。"""
    if target_date is None:
        return [base] if base else []
    out = [p for p in files if (_export_date(p) or target_date) >= target_date]
    return out or ([base] if base else [])

def find_shifted_detail_dates(workspace: Path) -> Dict[str, dict]:
    """
    找出“父回款当前筛选日 > 子表真实核销日”的历史核销明细。
    父记录发生新核销后会移动到最新核销日；本函数用于漏日补跑时还原旧日。
    """
    d = workspace / "01_智云导出"
    if not d.is_dir():
        return {}
    aliases = common.load_aliases()
    found: Dict[str, dict] = {}
    seen = set()
    for path in _role_files(d, "核销明细"):
        snapshot_date = _export_date(path)
        if snapshot_date is None:
            continue
        h, body = _sheet_rows(path)
        c = _need(h, "核销明细", ["回款记录NUM", "核销日期", "本次核销金额"], aliases)
        i_so = _col(h, "核销明细", "SO", aliases)
        for vals in body:
            ar = str(_get(vals, c["回款记录NUM"]) or "").strip()
            hd = common.norm_date(_get(vals, c["核销日期"]))
            so = str(_get(vals, i_so) or "").strip()
            amt = common.to_number(_get(vals, c["本次核销金额"]))
            if not ar or not so or amt is None or hd is None or hd >= snapshot_date:
                continue
            key = (hd, ar, so, round(float(amt), 2))
            if key in seen:
                continue
            seen.add(key)
            day = hd.isoformat()
            item = found.setdefault(
                day, {"rows": 0, "ars": set(), "sos": set(), "order_keys": set(), "sources": set()}
            )
            item["rows"] += 1
            item["ars"].add(ar)
            item["sos"].add(so)
            item["order_keys"].add(f"{ar}|{so}")
            item["sources"].add(path.name)
    return {
        day: {
            "rows": item["rows"],
            "ars": sorted(item["ars"]),
            "sos": sorted(item["sos"]),
            "order_keys": sorted(item["order_keys"]),
            "sources": sorted(item["sources"]),
        }
        for day, item in sorted(found.items())
    }

def assess_shifted_detail_dates(
    workspace: Path,
    date_from: Optional[dt.date] = None,
    date_to: Optional[dt.date] = None,
) -> Dict[str, dict]:
    """
    将被最新核销日挪走的历史子明细与该日判定结果对账；缺 AR/SO 才标记重跑。
    旧结果没有来源覆盖字段也能按 auto/hold/exception 三栏逐键检查。
    """
    found = find_shifted_detail_dates(workspace)
    out: Dict[str, dict] = {}
    for day, info in found.items():
        parsed_day = common.norm_date(day)
        if date_from and parsed_day and parsed_day < date_from:
            continue
        if date_to and parsed_day and parsed_day > date_to:
            continue
        stamp = day.replace("-", "")
        result_path = workspace / "04_产出" / f"判定结果_{stamp}.json"
        produced = set()
        if result_path.is_file():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
                for bucket in ("auto", "hold", "exception"):
                    for item in data.get(bucket) or []:
                        ar = str(item.get("ar") or "").strip()
                        so = str(item.get("so") or "").strip()
                        if ar and so:
                            produced.add(f"{ar}|{so}")
            except (OSError, ValueError, TypeError):
                produced = set()
        missing = sorted(set(info["order_keys"]) - produced)
        out[day] = {
            **info,
            "result": str(result_path) if result_path.is_file() else "",
            "missing_order_keys": missing,
            "needs_rerun": bool(missing),
        }
    return out

def reconcile_writeoff_details(
    payments: List[dict],
    parent_references: Dict[str, dict],
    raw_detail_rows: List[dict],
    target_date: Optional[dt.date],
) -> Tuple[List[dict], Dict[str, dict]]:
    """先按父AR纠正物理/系统重复，再形成目标日H和跨父AR累计R。"""
    raw_by_ar: Dict[str, List[dict]] = {}
    for row in raw_detail_rows:
        raw_by_ar.setdefault(row["ar"], []).append(row)

    audits: Dict[str, dict] = {}
    logical_rows: List[dict] = []
    unresolved_sos: Dict[str, List[str]] = {}
    for ar in sorted(set(parent_references) | set(raw_by_ar)):
        parent = parent_references.get(ar) or {
            "ar": ar, "amount_orig": None, "amount_local": None, "currency": ""
        }
        logical, audit = WDA.audit_parent_writeoffs(parent, raw_by_ar.get(ar, []))
        audit["ar"] = ar
        audits[ar] = audit
        if audit["status"] == "unresolved":
            for so in {
                str(row.get("so") or "").strip()
                for row in raw_by_ar.get(ar, [])
                if str(row.get("so") or "").strip()
            }:
                unresolved_sos.setdefault(so, []).append(ar)
            continue
        logical_rows.extend(logical)

    by_ar = {p["ar"]: p for p in payments}
    for p in payments:
        audit = audits.get(p["ar"]) or {
            "ar": p["ar"], "status": "normal", "comparison_basis": "unavailable",
            "raw_input_count": 0, "raw_record_count": 0, "logical_record_count": 0,
            "raw_total": 0.0, "logical_total": 0.0,
            "delta_raw": p.get("total_amount_local") or p.get("total_amount_orig"),
            "delta_dedup": p.get("total_amount_local") or p.get("total_amount_orig"),
            "duplicate_groups": [], "records": [], "ignored_record_count": 0,
            "physical_snapshot_duplicate_count": 0, "revoked_count": 0,
            "reason": "没有逐SO核销明细，沿用现有全额核销语义",
        }
        p["duplicate_writeoff_audit"] = audit
        p["writeoffs"] = {}
        p["writeoffs_local"] = {}
        p["cumulative_writeoffs"] = {}
        p["cumulative_writeoffs_local"] = {}
        p["_source_meta"]["raw_writeoff_rows"] = int(audit.get("raw_input_count") or 0)
        p["_source_meta"]["accounted_writeoff_rows"] = len(audit.get("records") or [])
        if audit.get("status") == "unresolved":
            p["_parent_audit_unresolved"] = {
                "code": audit.get("error_code") or "E_PARENT_WRITEOFF_MISMATCH",
                "reason": audit.get("reason") or "父回款金额守恒检查未通过",
            }

    # Preserve source expectations before selecting today's writeoffs. Audit
    # membership alone is not proof that a record reached its business date.
    source_keys_by_ar = {}
    for item in logical_rows:
        if item.get("date") is not None:
            source_keys_by_ar.setdefault(item["ar"], {}).setdefault(
                item["date"].isoformat(), set()
            ).add(f"{item['ar']}|{item['so']}")
    for p in payments:
        p["_source_order_keys_by_date"] = {
            day: sorted(keys) for day, keys in source_keys_by_ar.get(p["ar"], {}).items()
        }
    current_rows: List[dict] = []
    for item in logical_rows:
        p = by_ar.get(item["ar"])
        current_day = target_date if target_date is not None else (p or {}).get("hexiao_date")
        if p is not None and (current_day is None or item.get("date") == current_day):
            current_rows.append(item)
            w = p["writeoffs"]
            w[item["so"]] = round(w.get(item["so"], 0.0) + float(item["amount"]), 2)
            if item.get("amount_local") is not None:
                wl = p["writeoffs_local"]
                wl[item["so"]] = round(
                    wl.get(item["so"], 0.0) + float(item["amount_local"]), 2
                )
            if item.get("snapshot_date") and target_date and item["snapshot_date"] > target_date:
                p["_source_meta"]["historical_detail_rows"] += 1

    # 跨父 AR 的累计必须是“截至这一笔父回款”的运行累计，不能把目标日结束时的
    # 最终累计复制给当天每一笔父回款。否则同一 SO/SOD 的多笔小额回款会被每一笔
    # 都误判为已经结清，后续写入也就失去了逐笔拆行的依据。
    dated_logical_rows = [
        item for item in logical_rows
        if target_date is None or item.get("date") is None or item.get("date") <= target_date
    ]

    def sequence_key(item: dict) -> Tuple[str, str, str, str, str]:
        return (
            str(item.get("date") or ""),
            str(item.get("record_id") or ""),
            str(item.get("rowid") or ""),
            str(item.get("ar") or ""),
            str(item.get("so") or ""),
        )

    dated_logical_rows.sort(key=sequence_key)
    global_cumulative: Dict[str, float] = {}
    global_cumulative_local: Dict[str, float] = {}
    cumulative_after_parent_so: Dict[Tuple[str, str], float] = {}
    cumulative_local_after_parent_so: Dict[Tuple[str, str], float] = {}
    sequence_after_parent_so: Dict[Tuple[str, str], Tuple[str, str, str, str, str]] = {}
    for item in dated_logical_rows:
        so = item["so"]
        global_cumulative[so] = round(
            global_cumulative.get(so, 0.0) + float(item["amount"]), 2
        )
        cumulative_after_parent_so[(item["ar"], so)] = global_cumulative[so]
        if item.get("amount_local") is not None:
            global_cumulative_local[so] = round(
                global_cumulative_local.get(so, 0.0) + float(item["amount_local"]), 2
            )
            cumulative_local_after_parent_so[(item["ar"], so)] = global_cumulative_local[so]
        sequence_after_parent_so[(item["ar"], so)] = sequence_key(item)
    for p in payments:
        p_sos = {
            str(item.get("so") or "").strip()
            for item in raw_by_ar.get(p["ar"], []) + [row for row in logical_rows if row["ar"] == p["ar"]]
            if str(item.get("so") or "").strip()
        }
        inherited = sorted({ar for so in p_sos for ar in unresolved_sos.get(so, [])})
        if inherited and not p.get("_parent_audit_unresolved"):
            reason = (
                "同一SO的跨父AR历史核销存在未解决的父回款金额差异，累计回款不可安全计算："
                + ",".join(inherited)
            )
            p["_parent_audit_unresolved"] = {
                "code": "E_PARENT_WRITEOFF_MISMATCH",
                "reason": reason,
            }
            inherited_audit = audits.get(p["ar"])
            if inherited_audit is not None:
                inherited_audit["status_before_inherited_block"] = inherited_audit.get("status")
                inherited_audit["status"] = "unresolved"
                inherited_audit["error_code"] = "E_PARENT_WRITEOFF_MISMATCH"
                inherited_audit["reason"] = reason
                inherited_audit["inherited_unresolved_from"] = inherited
        # 全局累计按 SO 跨父 AR 使用。当前父回款即使没有逐单明细，也必须能看到
        # 其他父回款已经核销到同一 SO 的金额，才能从首个未结清订单续核。
        p["cumulative_writeoffs"] = dict(global_cumulative)
        p["cumulative_writeoffs_local"] = dict(global_cumulative_local)
        p["_writeoff_sequence_key_by_so"] = {}
        # 当前父回款涉及的 SO 要覆盖成“截至本父回款”的运行累计；没有被本父回款
        # 命中的其他 SO 仍保留目标日全局累计，供旧的跨父 AR 历史续核逻辑使用。
        for so in p_sos:
            key = (p["ar"], so)
            if key in cumulative_after_parent_so:
                p["cumulative_writeoffs"][so] = cumulative_after_parent_so[key]
            if key in cumulative_local_after_parent_so:
                p["cumulative_writeoffs_local"][so] = cumulative_local_after_parent_so[key]
            if key in sequence_after_parent_so:
                p["_writeoff_sequence_key_by_so"][so] = list(sequence_after_parent_so[key])
    return current_rows, audits

def load_exports(workspace: Path, target_date: Optional[dt.date] = None) -> List[dict]:
    """
    01_智云导出/ 四张表 → payments。缺件直接 InputError（不凑合、不猜）。

    文件按名字认，并按 target_date 选主快照。后续快照里真实核销日仍等于
    target_date 的子明细会自动回捞；其父回款和关联订单也一并补入本批。
    """
    d = workspace / "01_智云导出"
    if not d.is_dir():
        raise InputError(f"没有 {d}")
    aliases = common.load_aliases()

    hk_files = _role_files(d, "回款记录")
    xd_files = _role_files(d, "订单交付", "下单")
    mx_files = _role_files(d, "核销明细")
    sod_files = _role_files(d, "订单明细")
    p_hk = _base_export(hk_files, "回款记录", target_date, required=target_date is None)
    p_xd = _base_export(xd_files, "订单交付", target_date, required=target_date is None)
    p_mx = _base_export(mx_files, "核销明细", target_date, required=False)
    p_sod = _base_export(sod_files, "订单明细", target_date, required=False)

    if not p_hk and target_date is None:
        raise InputError(
            "01_智云导出/ 里没有「回款记录」表。\n"
            "  这一版取数只认单入口：先跑 fetch_zhiyun.py（回款记录按核销日期=T-1 + 关联子表），\n"
            "  它会一次产出 回款记录 / 订单交付 / 核销明细 / 订单明细 四份。"
        )
    if not p_xd and target_date is None:
        raise InputError(
            "01_智云导出/ 里没有「订单交付」表（每笔到账关联了哪几个 SO + 交付额）。\n"
            "  旧版的「回款核销对账」已废弃且不兼容——它拿不到 SOD、还会漏掉预收类。\n"
            "  请重新跑 fetch_zhiyun.py 取一次数。"
        )

    # ① 读取全部原始核销记录。不同核销记录NUM必须先保留；同一NUM跨快照
    #    的物理去重和明显超核销后的条件性业务纠正在父AR层统一完成。
    raw_detail_rows: List[dict] = []
    for path in _eligible_snapshots(mx_files, target_date, p_mx):
        h, body = _sheet_rows(path)
        c = _need(h, "核销明细", ["回款记录NUM", "核销日期", "本次核销金额"], aliases)
        i_record = _col(h, "核销明细", "核销记录NUM", aliases)
        i_rowid = _col(h, "核销明细", "rowid", aliases)
        i_so = _col(h, "核销明细", "SO", aliases)
        i_local = _col(h, "核销明细", "本次核销金额本币", aliases)
        i_currency = _col(h, "核销明细", "币种", aliases)
        i_rate = _col(h, "核销明细", "汇率", aliases)
        i_revoked = _col(h, "核销明细", "是否已撤销", aliases)
        snapshot_date = _export_date(path)
        for row_number, vals in enumerate(body, start=2):
            ar = str(_get(vals, c["回款记录NUM"]) or "").strip()
            hd = common.norm_date(_get(vals, c["核销日期"]))
            so = str(_get(vals, i_so) or "").strip()
            amt = common.to_number(_get(vals, c["本次核销金额"]))
            amt_local = common.to_number(_get(vals, i_local))
            if not ar or not so or amt is None:
                raise InputError(
                    f"核销明细原始行缺AR/SO/金额：{path.name} 第{row_number}行，禁止静默丢弃"
                )
            if target_date is not None and hd is not None and hd > target_date:
                continue
            raw_detail_rows.append({
                "record_id": str(_get(vals, i_record) or "").strip(),
                "rowid": str(_get(vals, i_rowid) or "").strip(),
                "ar": ar, "date": hd, "so": so, "amount": round(float(amt), 2),
                "amount_local": round(float(amt_local), 2) if amt_local is not None else None,
                "currency": str(_get(vals, i_currency) or "").strip(),
                "rate": common.to_number(_get(vals, i_rate)),
                "revoked": str(_get(vals, i_revoked) or "").strip(),
                "source": path.name, "snapshot_date": snapshot_date,
                "_input_index": len(raw_detail_rows),
            })
    detail_ars = {
        x["ar"] for x in raw_detail_rows
        if target_date is None or x.get("date") == target_date
    }
    if p_hk is None and not detail_ars:
        raise InputError(
            f"没有目标日 {target_date} 的回款主快照，也没有后续快照中的同日核销子明细"
        )

    # ② 回款记录：当天父记录 + 后续核销日文件中承载历史同日子明细的父记录。
    payments: List[dict] = []
    parent_references: Dict[str, dict] = {}
    seen_payments = set()
    for path in _eligible_snapshots(hk_files, target_date, p_hk):
        h, body = _sheet_rows(path)
        c = _need(h, "回款记录", ["AR", "核销日期"], aliases)
        for k in [
            "到账日期", "到账金额原币", "到账金额本币",
            "总到账金额原币", "总到账金额本币",
            "手续费", "手续费本币", "税费", "税费本币", "其他费用", "其他费用本币",
            "原币币种", "回款类型", "核销状态", "开票客户",
            "销售名称",
        ]:
            i = _col(h, "回款记录", k, aliases)
            if i is not None:
                c[k] = i
        snapshot_date = _export_date(path)
        for vals in body:
            ar = str(_get(vals, c["AR"]) or "").strip()
            parent_date = common.norm_date(_get(vals, c["核销日期"]))
            if not ar:
                continue
            info = {
                "ar": ar,
                "hexiao_date": target_date or parent_date,
                "parent_hexiao_date": parent_date,
                "arrival_date": common.norm_date(_get(vals, c.get("到账日期"))),
                "amount_orig": common.to_number(_get(vals, c.get("到账金额原币"))),
                "amount_local": common.to_number(_get(vals, c.get("到账金额本币"))),
                "total_amount_orig": common.to_number(
                    _get(vals, c.get("总到账金额原币"))
                ),
                "total_amount_local": common.to_number(
                    _get(vals, c.get("总到账金额本币"))
                ),
                "fee": common.to_number(_get(vals, c.get("手续费"))) or 0.0,
                "fee_local": common.to_number(_get(vals, c.get("手续费本币"))),
                "tax": common.to_number(_get(vals, c.get("税费"))) or 0.0,
                "tax_local": common.to_number(_get(vals, c.get("税费本币"))),
                "other_fee": common.to_number(_get(vals, c.get("其他费用"))) or 0.0,
                "other_fee_local": common.to_number(_get(vals, c.get("其他费用本币"))),
                "currency": str(_get(vals, c.get("原币币种")) or "").strip() or "人民币CNY",
                "huikuan_type": str(_get(vals, c.get("回款类型")) or "").strip(),
                "status": str(_get(vals, c.get("核销状态")) or "").strip(),
                "customer": str(_get(vals, c.get("开票客户")) or "").strip(),
                "sales_name": str(_get(vals, c.get("销售名称")) or "").strip(),
                "orders": [],
                "writeoffs": {},
                "writeoffs_local": {},
                "cumulative_writeoffs": {},
                "cumulative_writeoffs_local": {},
                "_source_meta": {
                    "payment_source": path.name,
                    "payment_snapshot_date": snapshot_date,
                    "historical_detail_rows": 0,
                    "recovered_deliveries": 0,
                },
            }
            _prepare_parent_totals(info)
            parent_references[ar] = info
            if ar in seen_payments:
                continue
            if target_date is not None and parent_date != target_date and ar not in detail_ars:
                continue
            seen_payments.add(ar)
            payments.append(info)
    if not payments:
        raise InputError(
            f"目标核销日没有可处理的回款记录：{target_date or (p_hk.name if p_hk else '')}"
        )
    by_ar = {p["ar"]: p for p in payments}

    # ③ 订单交付：先加载订单已核销金额和交付额，再做父 AR 审计。
    # 整笔回款的分类入口依赖这些订单字段，禁止在订单加载前提前挂账。
    order_map: Dict[Tuple[str, str], dict] = {}
    for path in _eligible_snapshots(xd_files, target_date, p_xd):
        h, body = _sheet_rows(path)
        c = _need(h, "订单交付", ["AR", "SO", "交付额原币"], aliases)
        i_written = _col(h, "订单交付", "订单已核销金额", aliases)
        i_written_local = _col(h, "订单交付", "订单已核销金额本币", aliases)
        i_deliver_local = _col(h, "订单交付", "交付额本币", aliases)
        i_rate = _col(h, "订单交付", "汇率", aliases)
        i_cur = _col(h, "订单交付", "币种", aliases)
        i_name = _col(h, "订单交付", "订单名称", aliases)
        i_delivery_date = _col(h, "订单交付", "项目交付日期", aliases)
        i_delivery_status = _col(h, "订单交付", "交付日期取数状态", aliases)
        for vals in body:
            ar = str(_get(vals, c["AR"]) or "").strip()
            so = str(_get(vals, c["SO"]) or "").strip()
            if not ar or not so or ar not in by_ar:
                continue
            key = (ar, so)
            amt = common.to_number(_get(vals, c["交付额原币"]))
            deliver_local = common.to_number(_get(vals, i_deliver_local))
            written_raw = _get(vals, i_written)
            written_local_raw = _get(vals, i_written_local)
            written_present = written_raw not in (None, "")
            written_local_present = written_local_raw not in (None, "")
            old = order_map.get(key)
            if old is None:
                old = {
                    "so": so, "deliver": None, "deliver_local": None,
                    "written_off": None, "written_off_local": None,
                    "written_off_present": False,
                    "written_off_local_present": False,
                    "rate": None, "currency": "", "name": "",
                    "delivery_date": None, "delivery_date_issue": "",
                    "_delivery_dates": set(), "_delivery_date_issues": set(),
                    "source": path.name, "snapshot_date": _export_date(path),
                }
                order_map[key] = old
            if amt is not None:
                old["deliver"] = amt
            if deliver_local is not None:
                old["deliver_local"] = deliver_local
            if written_present:
                old["written_off"] = common.to_number(written_raw)
                old["written_off_present"] = True
            if written_local_present:
                old["written_off_local"] = common.to_number(written_local_raw)
                old["written_off_local_present"] = True
            rate = common.to_number(_get(vals, i_rate))
            currency = str(_get(vals, i_cur) or "").strip()
            name = str(_get(vals, i_name) or "").strip()
            delivery_raw = _get(vals, i_delivery_date)
            delivery_status = str(_get(vals, i_delivery_status) or "").strip()
            if rate is not None:
                old["rate"] = rate
            if currency:
                old["currency"] = currency
            if name:
                old["name"] = name
            if delivery_raw not in (None, ""):
                delivery_date = common.norm_date(delivery_raw)
                if delivery_date is not None:
                    old["_delivery_dates"].add(delivery_date)
                else:
                    old["_delivery_date_issues"].add(
                        f"项目交付日期格式无效：{str(delivery_raw).strip()}"
                    )
            if delivery_status and not str(delivery_status).endswith("明确值"):
                old["_delivery_date_issues"].add(delivery_status)
            old["source"] = path.name
            old["snapshot_date"] = _export_date(path)

    for order in order_map.values():
        dates = set(order.pop("_delivery_dates", set()) or set())
        issues = set(order.pop("_delivery_date_issues", set()) or set())
        if len(dates) == 1 and not any("冲突" in str(x) for x in issues):
            order["delivery_date"] = next(iter(dates))
        elif len(dates) > 1:
            order["delivery_date"] = None
            issues.add("项目交付日期冲突：不同取数记录出现多个日期")
        if order.get("delivery_date") is None and not issues:
            issues.add("项目交付日期缺失：智云订单详情没有明确值")
        order["delivery_date_issue"] = "；".join(sorted(issues))

    # 核销明细可能补出下单表遗漏的 SO；先建立最低限度订单对象，保证父 AR
    # 审计能看到完整关联范围。金额仍不从核销明细反推订单已核销字段。
    for item in raw_detail_rows:
        if item["ar"] not in by_ar:
            continue
        if (item["ar"], item["so"]) not in order_map:
            order_map[(item["ar"], item["so"])] = {
                "so": item["so"], "deliver": None, "deliver_local": None, "rate": None,
                "written_off": None, "written_off_local": None,
                "written_off_present": False,
                "written_off_local_present": False,
                "delivery_date": None,
                "delivery_date_issue": "项目交付日期缺失：订单仅由核销明细补出",
                "currency": "", "name": "", "source": item.get("source") or "",
                "snapshot_date": item.get("snapshot_date"),
            }
    by_so_dates = {}
    for order in order_map.values():
        by_so_dates.setdefault(order["so"], []).append(order)
    for related in by_so_dates.values():
        dates = {order["delivery_date"] for order in related if order.get("delivery_date")}
        conflict = len(dates) > 1 or any(any(word in order.get("delivery_date_issue", "") for word in ("冲突", "格式无效")) for order in related)
        for order in related:
            if conflict:
                order.update(delivery_date=None, delivery_date_issue="项目交付日期冲突：同 SO 来源记录日期不一致")
            elif len(dates) == 1 and order.get("delivery_date") is None:
                order.update(delivery_date=next(iter(dates)), delivery_date_issue="",
                             delivery_date_basis="同 SO 唯一一致的项目交付日期")
    for (ar, _so), order in order_map.items():
        by_ar[ar]["orders"].append(order)

    # ④ 父 AR 审计：订单数据已就绪。整笔回款优先使用订单已核销金额；
    # 全部缺失时才允许使用完整交付额兜底。
    detail_rows, duplicate_audits = reconcile_writeoff_details(
        payments, parent_references, raw_detail_rows, target_date
    )

    # ⑤ 逻辑核销明细：同一核销记录NUM的跨快照物理重复已去除；
    # 不同记录NUM先保留，明显超核销时按父AR条件重复规则纠正或整笔挂账。
    for item in detail_rows:
        if item["ar"] not in by_ar:
            raise CoverageError(
                f"核销明细有父回款未取到：{item['ar']} / {item['so']} / {item['source']}"
            )
        p = by_ar[item["ar"]]
        if target_date is None and item["date"] is not None and p.get("hexiao_date") is not None:
            if item["date"] != p["hexiao_date"]:
                continue

    # ⑥ 订单明细（SO → SOD + 逐 SOD 交付额）；同一 SOD 取后续快照最新非空值。
    sod_map: Dict[Tuple[str, str], dict] = {}
    needed_sos = {o["so"] for p in payments for o in p["orders"]}
    for path in _eligible_snapshots(sod_files, target_date, p_sod):
        h, body = _sheet_rows(path)
        c = _need(h, "订单明细", ["SO", "SOD", "交付额原币"], aliases)
        for vals in body:
            so = str(_get(vals, c["SO"]) or "").strip()
            sod = str(_get(vals, c["SOD"]) or "").strip()
            if not so or not sod or so not in needed_sos:
                continue
            amt = common.to_number(_get(vals, c["交付额原币"]))
            key = (so, sod)
            if key not in sod_map or amt is not None:
                sod_map[key] = {"sod": sod, "deliver": amt, "source": path.name}
    sod_lines: Dict[str, List[dict]] = {}
    for (so, _sod), line in sod_map.items():
        sod_lines.setdefault(so, []).append(line)

    # 订单交付额为空时，只允许用该 SO 全部、唯一且非空的 SOD 交付额合计回补。
    for p in payments:
        for order in p["orders"]:
            if order.get("deliver") is not None:
                continue
            lines = sod_lines.get(order["so"]) or []
            if lines and all(x.get("deliver") is not None for x in lines):
                total = round(sum(float(x["deliver"]) for x in lines), 2)
                if total > TOL:
                    order["deliver"] = total
                    order["delivery_source"] = "订单明细SOD合计"
                    p["_source_meta"]["recovered_deliveries"] += 1
    for p in payments:
        p["sod_lines"] = sod_lines
        p["_duplicate_writeoff_audits"] = duplicate_audits
        p["_detailed_parent_ars"] = sorted({
            row["ar"]
            for row in raw_detail_rows
            if (
                target_date is None
                or row.get("date") is None
                or row.get("date") <= target_date
            )
        })
    return payments
