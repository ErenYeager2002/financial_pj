"""Shared amount tolerances and classification errors."""
from __future__ import annotations

from pathlib import Path
import amount_policy


HERE = Path(__file__).resolve().parent

TOL = float(amount_policy.TECHNICAL_EPSILON)  # 技术金额比较容差

ROUNDING_TAIL_TOL = float(amount_policy.CENT_TOLERANCE) + 0.001

BUSINESS_SETTLEMENT_TOL = float(amount_policy.BUSINESS_SETTLEMENT_TOLERANCE)

SUBSET_MAX_LINES = 22  # 超过这么多 SOD 就不硬凑子集，直接交人

class InputError(Exception):
    """输入缺件/结构不对 —— 脚本非 0 退出，绝不带病继续。"""

class CoverageError(Exception):
    """AR 覆盖率校验没过 —— 有到账没产出任何判定，说明逻辑漏了单。"""
