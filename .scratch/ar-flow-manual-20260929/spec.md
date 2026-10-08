# Flow manual false-positive repair

Scope: ar-hexiao-daily-lab balance.34. Preserve unrelated source changes and dashboard. No production finance rerun, data write, commit or push.

Confirmed against BAT-20260929-6EBB041B: 12 manual rows. Six old per-SO source records are identical to current source events and sum to the new whole receipt net entry; reuse those exact entries, never charge again. A carry-row match can target a verified member of its existing chain, not only the root. Single-SO FX delivery fallback with audited fees uses whole receipt net and the workbook exchange rate. A visible positive deduction prefix matching complete fetched source prefix binds existing deductions across months; later unknown deductions and balances remain intact. Status/color-only updates of already deducted receipts do not create a second carry row.

Evidence prerequisites: exact source event identities for prior per-SO entries, matching amounts/zero final balance; conserved current expression, unique visible SOs, complete source prefix and no conflicting owned event for cross-month legacy binding. Real business errors remain manual.

Validation: 12 actual records pass read-only write preflight; 302 focused flow tests passed. All 12 actual isolated-copy write/readback checks passed; all repeats produced zero changes; existing balances and original input unchanged. Final tightened prefix checks passed for all four affected records. Deployed 2026-09-29 17:51:42 Asia/Shanghai: balance.34, image sha256:6953dbec294990d94655632ff7d8017d06e32815b18d6356bd2107ca0190e55f. All five changed skill files match API/standard/discovery runtime. Tool enabled, global normal. Local diagnostics under .scratch/ar-manual-audit-20260929.
