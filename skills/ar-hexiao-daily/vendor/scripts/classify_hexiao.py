#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility entry point for AR classification.

Business responsibilities live in classification_*.py. Existing script callers
and diagnostic imports retain the same names and command-line arguments.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from execution_lineage import payment_source_lineage
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
import amount_policy
import argparse
import baseline_receipts as BR
import common
import datetime as dt
import fallback_allocation_ledger as FAL
import fallback_sequence as FS
import json
import re
import settlement_status
import sys
import writeoff_duplicate_audit as WDA
from classification_contract import (
    InputError,
    CoverageError,
    TOL,
    ROUNDING_TAIL_TOL,
    BUSINESS_SETTLEMENT_TOL,
    SUBSET_MAX_LINES,
    HERE
)
from classification_exports import (
    _sheet_rows,
    _col,
    _need,
    _get,
    _export_date,
    _role_files,
    _base_export,
    _eligible_snapshots,
    find_shifted_detail_dates,
    assess_shifted_detail_dates,
    reconcile_writeoff_details,
    load_exports,
    HUIKUAN_NAMES,
    EXPORT_DATE_RE
)
from classification_amounts import (
    _prepare_parent_totals,
    subset_sum_unique,
    _payment_local,
    _localize_amount,
    _hold,
    _hold_each_source_order,
    partial_split_guidance,
    _writeoff_business_amount,
    _order_delivery_local,
    _currency_key
)
from classification_expansion import (
    _allocate_parent_by_delivery,
    expand_payment,
    source_coverage,
    expand_payments
)
from classification_ledger import (
    LedgerIndex
)
from classification_decision import (
    _record_event_coverage,
    _mark_event_idempotent,
    classify_one
)
from classification_splitting import (
    _make_same_so_multi_sod_aggregate,
    _make_split_payment_chain,
    _expand_ambiguous_sod_waterfall
)
from classification_accrual import (
    _clear_new_accrual,
    _planned_settled_sods,
    _has_new_planned_accrual,
    _apply_so_accrual_gate,
    _historical_sod_writeoff_index,
    annotate_cross_month_accruals
)
from classification_summary import (
    _FLOW_WAIT_CODES,
    _flow_ready,
    build_ar_summary,
    _dist,
    serialize_result
)
from classification_runner import (
    classify_records,
    classify_records_by_year
)
from classification_cli import (
    payments_from_fixture,
    main
)

if __name__ == "__main__":
    sys.exit(main())
