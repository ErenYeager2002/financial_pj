"""Resolve local currency at the source row and preserve incomplete totals."""
from __future__ import annotations
import math
import common


def detail_local(row: dict):
    explicit = common.to_number(row.get('amount_local'))
    if explicit is not None and math.isfinite(explicit):
        return round(explicit, 2)
    amount = common.to_number(row.get('amount'))
    if amount is None or not math.isfinite(amount):
        return None
    currency = str(row.get('currency') or '').strip()
    if currency and common.is_cny(currency):
        return round(amount, 2)
    rate = common.to_number(row.get('rate'))
    if currency and rate is not None and math.isfinite(rate) and rate > 0:
        return round(amount * rate, 2)
    return None


def add_complete(totals: dict, key: str, value):
    """An unresolved constituent makes the entire prefix unresolved."""
    if value is None or (key in totals and totals[key] is None):
        totals[key] = None
    else:
        totals[key] = round(totals.get(key, 0.0) + value, 2)
    return totals[key]
