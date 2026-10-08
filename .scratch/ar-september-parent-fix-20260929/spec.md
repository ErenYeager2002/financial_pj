# September parent allocation and writeoff-only order hydration

Status: deployed and runtime verified at 2026-09-29 17:04:26 Asia/Shanghai. Version balance.33. API, standard worker and task-discovery worker each matched all six changed skill files. Tool enabled; global mode normal. Image sha256:6d8c7ba5324ef9c859c9691e42b279790f47cd66d1d2d66fc44492c84eb1330d.

## Confirmed faults

The latest September batch fixed balance.30. The relevant parent allocation and fetch modules remained identical in balance.32. Eighteen parent receipts were blocked by comparing cumulative workbook paid amounts with one parent receipt, treating shared dates as sufficient ambiguity, and requiring allocation history before using clearly earlier current-workbook receipts. One writeoff-only order lacked order detail hydration despite an explicit delivery date in Zhiyun.

## Scope

Only ar-hexiao-daily-lab. Current persisted workbook is authoritative. No historical allocation journal is introduced. No order numbers or customer exceptions in business logic. Existing itemized-source proof remains first. Ordinary skill, dashboard and unrelated source changes remain outside scope.

## Rules

- For fully located one-SOD order groups with conserved delivery/receivable structure, match exact parent total to current paid rows by source date, payment method and order relation.
- Require unique row subset, no overlap with another current parent identity, no repeated physical row, and no multi-row invented SOD posting.
- If there is no existing parent match, use paid balances only when every paid row is strictly earlier than arrival. Same-day, future, partially matching or structurally inconsistent rows continue through existing protected branches.
- New allocations consume delivery less current paid balance and same-batch reservations, in existing ascending-delivery order. Entire parent must fit. Existing complete parent matches carry applied-case proof and reserve no money again.
- Hydrate exact order details for SO identifiers found only in writeoff lines. Conflicting order details are errors; absent details are never fabricated.

## Acceptance

18 actual parent receipts: 11 already applied parents -> no writes; 7 new parents -> seven write plans totaling 9410.99, zero validation conflicts. Isolated workbook copy write/readback succeeds; repeated classification gives zero writes, zero conflicts. Original workbook SHA unchanged. Live SO detail lookup returns its actual delivery date and amount; supplemented export copy identifies the receipt as already present with zero writes. Two no-relation source exceptions are unchanged business input issues.

Targeted tests cover same-day distinct amounts, overlapping parent ownership, current balance and reservations, insufficient capacity, current-day uncertainty, unique subset ambiguity, preventing repeated use of one row, exact detail lookup and conflicts. Existing source-history, current workbook, recognition, allocation contract and fetch tests included: 93 passed.

Local evidence: .scratch/ar-september-audit-20260929/candidate-parent-regression.json, candidate-copy-readback.json, candidate-fetch-regression.json. Tests only write isolated local copies; no production finance rerun or financial write authorized.
