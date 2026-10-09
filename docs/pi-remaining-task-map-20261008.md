# 剩余任务映射与基线（R00）— 2026-10-08

来源：《财务平台剩余施工任务书 v1.0》（2026-10-08，基线 6476660）+ 当日只读现场核对。本文只做编号映射与证据对照，不替代各 R 任务的专项验收；不改仓库代码、不触发 CI、无财务操作。

## 分支与基线（实测 2026-10-08 10:30 GMT+8）

- GitHub origin/main = origin/refactor/full-platform-20260918 = `6476660d86ff9210da57ab87995c3245f252c890`（branches API 实测，与任务书 [S01] 一致）。"合入 main"维持移除；CI/部署状态独立核对。
- 重构工作树 HEAD = 6476660 + 20 项未提交变更（9 M + 11 ??）= F4.A 已部署实现，按 R00-T05 原样保留。
- 远程 clone 本地 `main` 引用陈旧（2cd58e9，落后 5），仅本地引用问题；clone 目录属 root，fetch 未强求。

## 原 F 编号 → R 任务映射（现场定义来源：pi-construction-resume-20261008.md 及各专项文档）

| 原编号 | 现场定义 | R 任务 | 状态（2026-10-08） |
|---|---|---|---|
| F1 | 封存前完整 Linux 后代停止证明 | 已完成（R02/R03 改动时回归） | 52 专项 + 1 真实 PG 通过；3 条历史 marker 未变，1 条仍需调查 |
| F2 / A24 | 按容量筛候选再取 100 条 | 已完成（R05 回归责任） | 11 PG + 23 通过；只读浏览器验收 |
| F4.A | 各次执行元数据只读展示 | R01 | **已完成**：13 专项 0 skip、双轴审查、前后端上线、只读浏览器验收；commit/push 未做 |
| F4.B | 不可变 prepared refs 锚点（Popen 前登记） | R02 前置（任务书未单列） | 规格 ready-for-agent（.scratch/pi-cw06-prepared-anchor/），实施会话进行中 |
| F4 剩余 | 多 attempt 进程/业务调查、管理员条件处置 | R02 | 未完成 |
| F5 | 发布实际文件 + DB 故障矩阵 | R03 | 未完成 |
| F3 | 安全有限重试 | R04 | 未完成 |
| A25 | 维护任务有界执行机会 | R05 | 未完成 |
| F6 | 生命周期 fixture | R07 | 未完成 |
| G4 | 全 Pi 浏览器矩阵 | R09 | 未完成 |
| CW09 | 能力权限/外联/副作用盘点 | R10 + R11 | 字段盘点已有（21 固定/16 原生观察数），差额未完成 |
| CW10 | DeerFlow 展示组件 | R13 | 条件任务，G1–G5 未满足 |
| CW11 | 终验 | R14 | 未完成 |

无 unmapped。原规范附件 [S11] 未在远程落盘；以上定义逐条来自现场文档，非猜测。

## 运行组件基线（2026-10-08 10:30 只读核对）

| 组件 | 版本/镜像 | 状态 |
|---|---|---|
| api-1 / worker-standard-1 / worker-task-discovery-1 | dca460d79055 | api healthy；Worker 无 Docker Health 字段记 running |
| next-1 | b8990adbbaed | Up |
| worker-agent-1 | 03e4a1f08e0d | Up |
| postgres-1 | postgres:16-alpine | healthy；alembic_version = f4b5c6d7e8f9（工作树迁移文件含对应版本） |
| gateway-1 | caddy:2-alpine | 纯 HTTP（auto_https off）宿主 8443；/maintenance/status = normal |
| pi_runtime_manager.py | 磁盘 sha256 63ad2e89…f1f678（与 10-07 审计一致） | 进程加载版本无法读回，标 unknown |
| F4.A 部署抽验 | 容器内 ar_attempt_history.py sha256 = 30b886da…f61b1439 = 工作树同文件 | 运行↔源码一致 |

## 93 项证据对照口径

- 有明确通过记录：F1（52+1PG）、F2/A24（11PG+23）、F4.A（13）。三组数字不相加为 93 项通过；A24 标"报告已通过，相关改动需回归"。
- 其余各项按任务书附录责任映射逐条对证据；未见逐项证据记"待核对/待执行"，不写 pass/fail。

## 可接续任务队列（按现场差额更新）

1. F4.B（规格 ready-for-agent，实施会话进行中，不重复开工）
2. R02（F4 剩余）→ R03（F5）
3. 并行隔离准备：R04（消费 R10）、R05、R07、R08、R10、R12.A（F1 合同缺口小补丁）
4. R11 → R09（G4）→ R13（CW10 条件）→ R14 终验
5. F4.A commit/push：待用户授权

## 进度入口

- 当前唯一进度入口：docs/pi-construction-resume-20261008.md
- 旧入口 docs/refactor/progress.md 顶部已补指针（2026-10-08），历史正文不改写

## 补记：R12.A 合同缺口已闭合（2026-10-08 10:57 实测）

- 工作树 `contracts/financial-platform.openapi.json`（143 路径）实测包含：`/api/workflows/{workflow_id}/execution/abandon`（F1 封存）、`/investigate`、`/recover`、`/api/pi-runtime/sessions/{session_id}/capabilities`、`/deliveries/{request_id}`、`/history`；模型含 `AbandonRequest`、`ArAttemptHistoryItem`、`ArAttemptHistoryRead`；`generated.ts` 含 AbandonRequest 引用 4 处。该缺口由 F4.A 轮次完整重新生成合同闭合（其文档记录的"原快照漏 4 路径及 AbandonRequest"已验证修复）。
- 检查命令（web/package.json 实测）：`pnpm --dir web contracts:generate` / `contracts:check`（openapi-typescript --check）；F4.A 轮次已运行通过，被测版本 = 6476660 + F4.A 未提交变更。
- CI 状态：head_sha=6476660 的 Actions 运行数今日复查仍为 **0**（工作流触发为 pull_request/workflow_dispatch）。R12.B（逐补丁重生成 + 最终候选完整 CI）**blocked**：需推送/手动 dispatch 授权；不记为通过也不记为失败。

## 补记：R10 能力盘点差额已落实（2026-10-08 11:20）

- 交付：`docs/pi-cw09-capability-effects-20261008.md` + `.json`（schema pi-capability-effects-v1，37 条目：21 固定 + 16 原生 pinned）。逐项给出副作用六类归类、外联系统、输入输出、恢复事实与证据文件行。派生索引可从权威来源（tool.yaml / 原生固定包 / 批准记录）重建，非第二份业务正本（R10-T06 当场演示重建）。
- 关键事实：tool.yaml 21/21 有 risk 声明块但**均无恢复规则字段**；单项恢复规则仅 ar-hexiao-daily（含 lab）与 consolidated-statements 在 SKILL.md 文档化，其余 34 项记"无文档化"（不补猜）。
- **缺陷 D-01**：`order-daily-summary`（disabled）tool.yaml 声明 `access=uploaded_export`，但 SKILL.md/README 为直连登录智云 `192.168.10.167:18880` 取数——声明与文档行为不一致，待修正声明或文档。
- 条件行为标注：`withholding-report-rename` 默认出副本，仅用户明示时 `--mode rename` 改原件且先备份（original_modify 条件项）；`jdy-cashflow-export` 的 browser_rpa 是否有写动作细项标 unknown。
- 磁盘观察：原生 `ar-hexiao-daily`、`consolidated-statements` 各存在旧固定目录（17f7f96、55a8065），当前 pinned 以 register 为准（23a456a / aab80a8）。
- 证据复用（未重跑）：R10-T01/T02 权限映射与默认空绑定、T04 委托失效、T05 服务端独立拒绝——引用 pi-cw09-boundary-progress.md 与 resume 文档源码确认边界；R10-T03 由本索引落实。
- 未覆盖（保留缺口，不影响 R04 消费）：逐项"环境可执行/业务验收"两状态本轮未实测；原生 16 项的恢复规则文档化缺口待各 skill 后续维护时补齐。
