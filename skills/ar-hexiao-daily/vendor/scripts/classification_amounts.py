"""Normalize receipt amounts and currency, with allocation helpers."""
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import common
from classification_contract import SUBSET_MAX_LINES, TOL


def _prepare_parent_totals(p: dict) -> dict:
    """Prefer Zhiyun's total receipt; otherwise compute arrival plus charges."""
    amount_orig = common.to_number(p.get("amount_orig"))
    amount_local = common.to_number(p.get("amount_local"))
    existing_total_source = p.get("_parent_total_source")
    original_marker = p.get("_parent_total_orig_explicit")
    local_marker = p.get("_parent_total_local_explicit")
    explicit_total_orig = (
        None
        if existing_total_source == "computed_amount_plus_fee_tax" or original_marker is False
        else common.to_number(p.get("total_amount_orig"))
    )
    explicit_total_local = (
        None
        if existing_total_source == "computed_amount_plus_fee_tax" or local_marker is False
        else common.to_number(p.get("total_amount_local"))
    )
    if original_marker is None:
        p["_parent_total_orig_explicit"] = explicit_total_orig is not None
    if local_marker is None:
        p["_parent_total_local_explicit"] = explicit_total_local is not None
    p.pop("_charge_error", None)
    components = []
    for name, local_name in (
        ("fee", "fee_local"),
        ("tax", "tax_local"),
        ("other_fee", "other_fee_local"),
    ):
        original = common.to_number(p.get(name)) or 0.0
        local = common.to_number(p.get(local_name))
        if float(original) < -TOL or (local is not None and float(local) < -TOL):
            p["_charge_error"] = "手续费、税费或其他费用出现负数，无法按总到账金额自动核销"
        components.append((name, round(float(original), 2), local))

    charge_orig = round(sum(value for _name, value, _local in components), 2)
    local_values = []
    for _name, original, explicit_local in components:
        if explicit_local is not None:
            local_values.append(float(explicit_local))
        elif abs(original) <= TOL:
            local_values.append(0.0)
        elif common.is_cny(p.get("currency") or ""):
            local_values.append(original)
        elif (
            amount_orig is not None
            and amount_local is not None
            and abs(float(amount_orig)) > TOL
        ):
            local_values.append(original * float(amount_local) / float(amount_orig))
        else:
            local_values = []
            break

    charge_local = round(sum(local_values), 2) if len(local_values) == len(components) else None
    p["charge_amount_orig"] = charge_orig
    p["charge_amount_local"] = charge_local
    has_explicit_total = explicit_total_orig is not None or explicit_total_local is not None
    if has_explicit_total:
        total_orig = explicit_total_orig
        total_local = explicit_total_local
        if total_orig is None and total_local is not None:
            if common.is_cny(p.get("currency") or ""):
                total_orig = total_local
            elif (
                amount_orig is not None
                and amount_local is not None
                and abs(float(amount_local)) > TOL
            ):
                total_orig = round(
                    float(total_local) * float(amount_orig) / float(amount_local), 2
                )
        if total_local is None and total_orig is not None:
            if common.is_cny(p.get("currency") or ""):
                total_local = total_orig
            elif (
                amount_orig is not None
                and amount_local is not None
                and abs(float(amount_orig)) > TOL
            ):
                total_local = round(
                    float(total_orig) * float(amount_local) / float(amount_orig), 2
                )
        total_source = "zhiyun_total_received"
    else:
        total_orig = (
            round(float(amount_orig) + charge_orig, 2)
            if amount_orig is not None
            else None
        )
        total_local = (
            round(float(amount_local) + float(charge_local), 2)
            if amount_local is not None and charge_local is not None
            else None
        )
        total_source = "computed_amount_plus_fee_tax"
    p["total_amount_orig"] = total_orig
    p["total_amount_local"] = total_local
    p["_parent_total_source"] = total_source
    return p

def subset_sum_unique(
    lines: List[dict], target: float, max_lines: int = SUBSET_MAX_LINES
) -> Optional[List[dict]]:
    """
    在 SOD 行里凑出金额恰好 = target 的**唯一**子集。
    多解 / 无解 / 行太多 → None（交给人，绝不随便挑一个）。
    """
    usable = [x for x in lines if x.get("deliver") is not None]
    if not usable or len(usable) > max_lines:
        return None
    cents = [int(round(float(x["deliver"]) * 100)) for x in usable]
    tgt = int(round(target * 100))
    if tgt <= 0:
        return None
    # ways[sum] = (方案数(封顶2), 一个见证掩码)
    ways: Dict[int, Tuple[int, int]] = {0: (1, 0)}
    for i, v in enumerate(cents):
        if v <= 0:
            continue
        nxt = dict(ways)
        for s, (n, mask) in ways.items():
            s2 = s + v
            if s2 > tgt:
                continue
            n0, m0 = nxt.get(s2, (0, 0))
            nxt[s2] = (min(n0 + n, 2), m0 if n0 else (mask | (1 << i)))
        ways = nxt
    n, mask = ways.get(tgt, (0, 0))
    if n != 1:
        return None
    return [usable[i] for i in range(len(usable)) if mask & (1 << i)]

def _payment_local(p: dict, rates: Dict[str, float]) -> Tuple[Optional[float], Optional[str]]:
    """到账本币：系统给了就用系统的，没给才按汇率算。"""
    if p.get("amount_local") is not None:
        return float(p["amount_local"]), None
    return common.compute_local_amount(p.get("amount_orig"), p.get("currency") or "", rates)

def _localize_amount(
    amount_orig: Optional[float],
    p: dict,
    rates: Dict[str, float],
    *,
    explicit_local: Optional[float] = None,
    explicit_orig: Optional[float] = None,
    row_rate: Optional[float] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """
    把订单/SOD原币金额换成本币。优先级：
    子核销本币 → 订单汇率 → 父回款原/本币反算 → 命令行汇率。

    父/子同时给出原币和本币时，反算只用于同币种SOD的确定性换算，
    不是在多个SO之间猜分摊。
    """
    if amount_orig is None:
        return None, "E7"
    amount = float(amount_orig)
    currency = p.get("currency") or ""
    if common.is_cny(currency):
        return round(amount, 2), None
    if explicit_local is not None:
        base_orig = common.to_number(explicit_orig)
        if base_orig is not None and abs(float(base_orig)) > TOL:
            return round(amount * float(explicit_local) / float(base_orig), 2), None
        if abs(amount) <= TOL:
            return 0.0, None
    rate = common.to_number(row_rate)
    if rate is not None and float(rate) > 0:
        return round(amount * float(rate), 2), None
    parent_orig = common.to_number(p.get("amount_orig"))
    parent_local = common.to_number(p.get("amount_local"))
    if (
        parent_orig is not None
        and parent_local is not None
        and abs(float(parent_orig)) > TOL
    ):
        return round(amount * float(parent_local) / float(parent_orig), 2), None
    return common.compute_local_amount(amount, currency, rates)

def _hold(p: dict, code: str, reason: str, so: str = "", sod: str = "", **extra) -> dict:
    rec = {
        "ar": p["ar"], "so": so, "sod": sod,
        "customer": p.get("customer") or "",
        "sales_name": p.get("sales_name") or "",
        "amount_orig": None,
        "currency": p.get("currency") or "人民币CNY",
        "hexiao_date": p.get("hexiao_date"),
        "shoukuan_date": p.get("arrival_date"),
        "status": p.get("status") or "",
        "huikuan_type": p.get("huikuan_type") or "",
        "fee": p.get("charge_amount_orig") or 0.0,
        "arrival_total": p.get("amount_orig"),
        "business_arrival_total": p.get("total_amount_orig"),
        "forced_code": code,
        "forced_reason": reason,
    }
    rec.update(extra)
    return rec

def _hold_each_source_order(p: dict, code: str, reason: str) -> List[dict]:
    """付款级卡点也按来源 SO 展示；有多个订单时不再只留一条 AR 总挂账。"""
    sos = set((p.get("writeoffs") or {}).keys())
    if not sos:
        sos = {str(o.get("so") or "").strip() for o in (p.get("orders") or [])}
    sos.discard("")
    if not sos:
        return [_hold(p, code, reason)]
    return [_hold(p, code, reason, so=so) for so in sorted(sos)]

def partial_split_guidance(
    latest_delivery: float,
    current_received: float,
    *,
    initial_receivable: Optional[float] = None,
    existing_received: Optional[float] = None,
) -> str:
    """按 2026-07-29 定稿口径生成部分回款拆行说明。"""
    latest = round(float(latest_delivery), 2)
    current = round(float(current_received), 2)
    existing = round(float(existing_received or 0.0), 2)
    cumulative = round(existing + current, 2)
    remaining = round(latest - cumulative, 2)

    if remaining < -TOL:
        balance = (
            f"表内历史回款 {existing:.2f} + 本次 {current:.2f} = {cumulative:.2f}，"
            f"已超过智云最新交付 {latest:.2f}；交付额下降/超收口径未定，先人工核对，禁止自动写。"
        )
    elif remaining <= TOL:
        balance = (
            f"表内历史回款 {existing:.2f} + 本次 {current:.2f} = {cumulative:.2f}，"
            f"已回满智云最新交付 {latest:.2f}。"
        )
    else:
        balance = (
            f"智云最新实际交付 {latest:.2f}，表内历史回款 {existing:.2f}，"
            f"本次实际回款 {current:.2f}；本次后累计回款 {cumulative:.2f}，"
            f"实际未收 = 最新交付 − 累计实际回款 = {remaining:.2f}。"
        )

    if remaining <= TOL:
        return balance + " 请核对历史回款、交付金额和 SOD 归属；当前不提供新增未收行指令。"

    if initial_receivable is None:
        baseline = (
            "盈亏表原始应收基线不能被最新交付额覆盖：先汇总这张单拆行前的原始应收，"
            "未收行应收填实际未收；已收侧应收合计 = 原始应收合计 − 实际未收，"
            "保证拆行后应收合计仍等于原始基线。"
        )
    else:
        initial = round(float(initial_receivable), 2)
        paid_side = round(initial - max(remaining, 0.0), 2)
        baseline = (
            f"这张单盈亏表原始应收合计 {initial:.2f} 必须保持不变："
            f"未收行应收填 {max(remaining, 0.0):.2f}，"
            f"已收侧应收合计填 {paid_side:.2f}，两边仍合计 {initial:.2f}。"
        )

    return (
        balance
        + baseline
        + f" 本次已收行回款明细填 {current:.2f}、结账填「是」、日期和方式照到账/核销月份规则；"
        "其下新增未收行，结账填「否」，回款明细、日期、方式留空。"
        f" 累计回款未达到最新交付 {latest:.2f} 前，两行计提都留空；"
        f"只有累计回款达到 {latest:.2f} 时，最后结清行计提才填 {latest:.2f}。"
    )

def _writeoff_business_amount(
    amount: Optional[float],
    *,
    explicit_local: Optional[float] = None,
    explicit_orig: Optional[float] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """
    智云核销业务金额口径。

    有“本次核销金额本币”时按同一子核销金额的原/本币比例落到当前 SOD；
    没有本币列时直接使用“本次核销金额”，不再反向要求父回款汇率，也不读取、
    扣减或分配手续费。调用方必须保证金额来自同一 SO 的核销明细或最新交付额。
    """
    value = common.to_number(amount)
    if value is None:
        return None, "E7"
    local = common.to_number(explicit_local)
    original = common.to_number(explicit_orig)
    if local is not None and original is not None and abs(float(original)) > TOL:
        return round(float(value) * float(local) / float(original), 2), None
    return round(float(value), 2), None

def _order_delivery_local(
    amount_orig: Optional[float], p: dict, rates: Dict[str, float], order: Optional[dict],
    *, explicit_local: Optional[float] = None, explicit_orig: Optional[float] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """订单交付本币只认智云明确本币值或该订单自己的汇率。"""
    order = order or {}
    amount = common.to_number(amount_orig)
    if amount is None:
        return None, "E7"
    currency = order.get("currency") or p.get("currency") or ""
    if common.is_cny(currency):
        return round(float(amount), 2), None
    local = common.to_number(explicit_local)
    original = common.to_number(explicit_orig)
    if local is not None and original is not None and abs(float(original)) > TOL:
        return round(float(amount) * float(local) / float(original), 2), None
    rate = common.to_number(order.get("rate"))
    if rate is not None and float(rate) > 0:
        return round(float(amount) * float(rate), 2), None
    return None, "E6"

def _currency_key(value: Any) -> str:
    """用于父回款原币与订单原币的保守可比性判断。"""
    text = str(value or "").strip().upper().replace(" ", "")
    if common.is_cny(text):
        return "CNY"
    return text
