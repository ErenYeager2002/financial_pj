# CW09 能力副作用/外联/恢复派生索引 — 2026-10-08

派生自权威来源（tool.yaml、原生固定包、批准记录），可从来源重建；不是第二份业务正本。
类别：immutable_in_independent_out=不可变输入独立输出；external_read=外部只读；workcopy_modify=工作副本修改；original_modify=原件修改；external_write=外部写；unknown=未知。

| 形态 | ID | 状态 | 副作用 | 外联 | 恢复事实 |
|---|---|---|---|---|---|
| fixed | ar-hexiao-daily | published | external_read+workcopy_modify | 智云 | 有 |
| fixed | ar-hexiao-daily-lab | published | external_read+workcopy_modify | 智云 | 有 |
| fixed | jdy-cashflow-export | disabled | external_read+unknown | 金蝶云 | 无文档化 |
| fixed | jdy-cashflow-reconcile | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | labor-invoice-check | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | compliance-spot-check | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | task-clarifier | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | env-doctor | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | reconcile-bank | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | receivables-merge-and-split | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | dreame-ar-progress-diff | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | pdf-compress | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | withholding-report-rename | disabled | immutable_in_independent_out+original_modify | 电子税务局 | 无文档化 |
| fixed | xlsx | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | pdf | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | pptx | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | docx | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | order-daily-summary | disabled | external_read+immutable_in_independent_out | 智云(192.168.10.167:18880) | 无文档化 |
| fixed | project-detail-to-ledger | disabled | immutable_in_independent_out | 无 | 无文档化 |
| fixed | consolidated-statements | disabled | external_read+immutable_in_independent_out | 金蝶 | 有 |
| fixed | dept-expense-alloc | disabled | external_read+immutable_in_independent_out | 用友 | 无文档化 |
| native | ar-hexiao-daily | installed:23a456a | external_read+workcopy_modify | 智云 | 有 |
| native | consolidated-statements | installed:aab80a8 | external_read+immutable_in_independent_out | 金蝶 | 有 |
| native | dept-expense-alloc | installed:17f7f96 | external_read+immutable_in_independent_out | 用友 | 无文档化 |
| native | docx | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | dreame-ar-progress-diff | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | labor-invoice-check | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | pdf | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | pptx | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | project-detail-to-ledger | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | receivables-merge | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | split-by-sales | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | xlsx | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | withholding-report-rename | installed:17f7f96 | immutable_in_independent_out+original_modify | 电子税务局 | 无文档化 |
| native | kingdee-gl-import | installed:17f7f96 | immutable_in_independent_out | 无 | 无文档化 |
| native | kingdee-posting | installed:17f7f96 | external_read+immutable_in_independent_out | 金蝶开放平台；金蝶云星辰网页；智云 | 无文档化 |
| native | pl-dept-report | installed:17f7f96 | external_read+immutable_in_independent_out | 金蝶 | 无文档化 |

## 缺陷

- **order-daily-summary** (fixed): D-01: tool.yaml 声明 access=uploaded_export，但 SKILL.md/README 为直连登录智云取数；声明与文档行为不一致

## 备注

- **jdy-cashflow-export**: browser_rpa 经外部系统会话操作；是否存在点击类写动作未逐项核实，细项标 unknown
- **withholding-report-rename**: original_modify 为条件行为：需用户明示且脚本先备份
- **ar-hexiao-daily**: 磁盘另有 17f7f96 旧固定目录，当前 pinned 为 23a456a
- **consolidated-statements**: 磁盘另有 17f7f96/55a8065 旧固定目录
- **withholding-report-rename**: original_modify 为条件行为
- **kingdee-gl-import**: 缺库时 pip 清华/阿里/中科大/默认源属环境准备外联，非业务外联

明细（输入输出、证据文件行）见同目录 pi-cw09-capability-effects-20261008.json。
