# -*- coding: utf-8 -*-
"""核销明细应保留本币金额，并累计目标日之前的历史核销。"""
import datetime as dt
from pathlib import Path

import openpyxl

import classify_hexiao as C


def _xlsx(path: Path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_loader_keeps_current_local_and_cross_ar_cumulative_writeoffs(tmp_path):
    export_dir = tmp_path / "01_智云导出"
    _xlsx(
        export_dir / "回款记录_20260724.xlsx",
        [
            "回款记录ID", "核销日期", "到账日期", "到账金额/原币", "到账金额/本币",
            "手续费/原币", "原币币种", "回款类型", "核销状态", "开票客户",
        ],
        [
            ["AR0", dt.date(2026, 6, 11), dt.date(2026, 6, 11), 3053.13, 21949.18,
             0, "美元USD", "", "核销成功", "客户甲"],
            ["AR1", dt.date(2026, 7, 24), dt.date(2026, 7, 24), 1030.47, 7410.12,
             0, "美元USD", "", "核销成功", "客户甲"],
        ],
    )
    _xlsx(
        export_dir / "订单交付_20260724.xlsx",
        ["回款记录ID", "SO", "交付额/原币", "汇率", "结算币种", "订单名称",
         "项目交付日期", "交付日期取数状态"],
        [["AR1", "SO1", 4083.60, None, "美元USD", "订单甲",
          dt.date(2025, 8, 13), "订单详情明确值"]],
    )
    _xlsx(
        export_dir / "核销明细_20260724.xlsx",
        ["核销记录NUM", "rowid", "回款记录NUM", "核销日期",
         "本次核销金额", "本次核销金额/本币", "币种", "汇率",
         "SO", "是否已撤销"],
        [
            # 历史首款来自另一父回款 AR0；累计必须仍按 SO 合并到当前 AR1。
            ["HX0", "", "AR0", dt.date(2026, 6, 11), 3053.13, 21949.18,
             "美元USD", None, "SO1", "否"],
            ["HX1", "", "AR1", dt.date(2026, 7, 24), 1030.47, 7410.12,
             "美元USD", None, "SO1", "否"],
        ],
    )
    _xlsx(
        export_dir / "订单明细_20260724.xlsx",
        ["SO", "SOD", "交付额/原币"],
        [["SO1", "SOD1", 4083.60]],
    )

    payment = C.load_exports(tmp_path, dt.date(2026, 7, 24))[0]
    assert payment["writeoffs"] == {"SO1": 1030.47}
    assert payment["writeoffs_local"] == {"SO1": 7410.12}
    assert payment["cumulative_writeoffs"] == {"SO1": 4083.60}
    assert payment["cumulative_writeoffs_local"] == {"SO1": 29359.30}
    assert payment["orders"][0]["delivery_date"] == dt.date(2025, 8, 13)


def test_loader_preserves_zhiyun_total_received_for_parent_audit(tmp_path):
    export_dir = tmp_path / "01_智云导出"
    _xlsx(
        export_dir / "回款记录_20260820.xlsx",
        [
            "回款记录ID", "核销日期", "到账日期", "到账金额/原币", "到账金额/本币",
            "总到账金额/原币", "总到账金额/本币", "手续费/原币", "原币币种",
            "回款类型", "核销状态", "开票客户",
        ],
        [[
            "AR1", dt.date(2026, 8, 20), dt.date(2026, 8, 20), 26732.38, 26732.38,
            28350.0, 28350.0, 12.90, "人民币CNY", "整笔回款", "核销成功", "客户甲",
        ]],
    )
    _xlsx(
        export_dir / "订单交付_20260820.xlsx",
        [
            "回款记录ID", "SO", "交付额/原币", "订单已核销金额", "结算币种",
            "订单名称", "项目交付日期", "交付日期取数状态",
        ],
        [[
            "AR1", "SO1", 28350.0, 28350.0, "人民币CNY", "订单甲",
            dt.date(2025, 8, 13), "订单详情明确值",
        ]],
    )

    payment = C.load_exports(tmp_path, dt.date(2026, 8, 20))[0]

    assert payment["amount_orig"] == 26732.38
    assert payment["total_amount_orig"] == 28350.0
    assert payment["total_amount_local"] == 28350.0
    assert payment["_parent_total_source"] == "zhiyun_total_received"


def test_loader_audits_explicit_total_against_order_original_amounts(tmp_path):
    export_dir = tmp_path / "01_智云导出"
    _xlsx(
        export_dir / "回款记录_20260820.xlsx",
        [
            "回款记录ID", "核销日期", "到账日期", "到账金额/原币", "到账金额/本币",
            "总到账金额/原币", "总到账金额/本币", "手续费/原币", "原币币种",
            "回款类型", "核销状态", "开票客户",
        ],
        [[
            "AR1", dt.date(2026, 8, 20), dt.date(2026, 8, 20), 30.0, 30.0,
            30.0, 30.0, 0, "人民币CNY", "整笔回款", "核销成功", "客户甲",
        ]],
    )
    _xlsx(
        export_dir / "订单交付_20260820.xlsx",
        [
            "回款记录ID", "SO", "交付额/原币", "汇率", "结算币种",
            "订单名称", "项目交付日期", "交付日期取数状态",
        ],
        [
            [
                "AR1", "SO1", 10.0, 7.0, "美元USD", "订单甲",
                dt.date(2025, 8, 13), "订单详情明确值",
            ],
            [
                "AR1", "SO2", 20.0, 7.0, "美元USD", "订单乙",
                dt.date(2025, 8, 14), "订单详情明确值",
            ],
        ],
    )

    payment = C.load_exports(tmp_path, dt.date(2026, 8, 20))[0]
    audit = payment["duplicate_writeoff_audit"]

    assert audit["status"] == "delivery_fallback"
    assert audit["comparison_basis"] == "delivery_fallback_original"
    assert audit["effective_order_amount_count"] == 2
    assert payment["writeoffs"] == {"SO1": 10.0, "SO2": 20.0}
    assert payment["writeoffs_local"] == {}


def test_whole_foreign_delivery_fallback_audits_original_but_writes_local(tmp_path):
    export_dir = tmp_path / "01_智云导出"
    _xlsx(
        export_dir / "回款记录_20260902.xlsx",
        [
            "回款记录ID", "核销日期", "到账日期", "到账金额/原币", "到账金额/本币",
            "总到账金额/原币", "总到账金额/本币", "手续费/原币", "原币币种",
            "回款类型", "核销状态", "开票客户",
        ],
        [[
            "AR26090004", dt.date(2026, 9, 2), dt.date(2026, 9, 2),
            8833.0, 63526.05, 8844.0, None, 11.0, "美元USD",
            "整笔回款", "核销成功", "客户甲",
        ]],
    )
    _xlsx(
        export_dir / "订单交付_20260902.xlsx",
        [
            "回款记录ID", "SO", "订单已核销金额", "订单已核销金额/本币",
            "交付额/原币", "交付额/本币", "汇率", "结算币种", "订单名称",
            "项目交付日期", "交付日期取数状态",
        ],
        [[
            "AR26090004", "SO26060803", None, None, 8844.0, 63605.16,
            7.1919, "美元USD", "订单甲", dt.date(2026, 6, 10), "订单详情明确值",
        ]],
    )
    _xlsx(
        export_dir / "订单明细_20260902.xlsx",
        ["SO", "SOD", "交付额/原币"],
        [["SO26060803", "SOD26061029", 8844.0]],
    )

    payment = C.load_exports(tmp_path, dt.date(2026, 9, 2))[0]
    audit = payment["duplicate_writeoff_audit"]

    assert audit["comparison_basis"] == "delivery_fallback_original"
    assert audit["delta"] == 0
    assert payment["writeoffs"] == {"SO26060803": 8844.0}
    assert payment["writeoffs_local"] == {"SO26060803": 63605.16}

    record = C.expand_payment(payment, {})[0]
    assert record["amount_local"] == 63605.16
    assert record["deliver_local"] == 63605.16

    ledger = C.LedgerIndex(synthetic={
        "so": {"SO26060803": [5657]},
        "sod": {"SOD26061029": [5657]},
        "rows": {
            5657: {
                "so": "SO26060803", "sod": "SOD26061029",
                "yingshou": 63605.16,
            }
        },
    })
    result = C.classify_one(record, ledger, {}, 0.0, 2026)
    assert result["bucket"] == "auto"
    assert result["five_cols"]["计提"] == 63605.16
    assert result["five_cols"]["回款明细"] == 63605.16
