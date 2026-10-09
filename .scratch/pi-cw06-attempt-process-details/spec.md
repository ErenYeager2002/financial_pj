# CW06 / F4.C-1: on-demand original-attempt process details

Status: ready-for-agent
Date: 2026-10-08
Depends on: accepted F4.B; docs/pi-cw06-prepared-anchor-progress-20261008.md final 04:36 UTC node
Primary authority: approved construction standard sections 10.3/10.7 and existing execution-read seam.

## 1. 固定接口与职责

原 GET `/api/workflows/{id}/execution` 新增 `include_process_details: bool = Query(False)`。`read_execution(workflow, *, include_process_details=False)` 保留旧行为，仅 true 时调用独立窄模块 `ar_attempt_process_details.py` 并附加可选 typed DTO；available=false 的历史返回同样允许附加 unknown/有限核查投影。

**原 `ArAttemptHistoryRead`/Item 完全不改**：它是 metadata-only，`process_evidence_checked` 为 `Literal[False]`；把已检查详情嵌进该对象会形成矛盾。因此新详情置于 `ArExecutionRead.process_details: ArAttemptProcessDetailsRead | None = None`。条目以 `action_id+attempt` 对应原历史元数据，legacy 条目 attempt=null，不能补造以前次数的身份。

初始加载、进度刷新、3秒调查轮询、原刷新按钮，以及 recover/investigate 两处 POST 的 `read_execution` 回包一律 default false。前端只有显式查看/重新检查进程详情请求 true，使用独立 loading/error/结果状态；不覆写 recovery_allowed/checkpoint。BFF 仅白名单转发此 query，沿原授权及错误处理；正式生成 OpenAPI JSON/TS，现有 GET/BFF 复用，无新 endpoint。

现有默认 GET 仍会进行原 recovery/write/abandon 安全检查；这里只保证不运行**新增全 attempt 核查**，不承诺整个 GET 纯 metadata 或墙钟 deadline。

## 2. 最小 typed DTO

所有公开模型 `extra=forbid`。reason 为固定枚举/中文映射，不返回异常原文。

| Read 字段 | 合同 |
|---|---|
| `schema_version` | Literal `ar-attempt-process-details-v1` |
| `metadata_snapshot_fingerprint` | 原 attempt_history 的64hex摘要；用于页面判断该详情属于哪份元数据，不是授权 token |
| `evidence_revision` | 原索引 revision，未知 null，不增修订号 |
| `registered_effect_coverage_complete` | bool；仅该次原登记 effect 引用读取完整，不能代表全 workflow 停止 |
| `whole_workflow_coverage` | Literal `unknown`；non-effect/独立调查未锚定，不能给 complete |
| `reason_codes` | 最多16个固定原因，包含缺证/预算/未锚定范围 |
| `observation_fingerprint` | 独立64hex；规范化注册摘要、核查结果及覆盖范围，只为只读观察；不更改原 metadata/recovery fingerprint |
| `items` | 最多256个 typed Item；按原历史 action_id+attempt 关联/稳定排序 |

| Item 字段 | 合同 |
|---|---|
| `action_id`、`attempt`、`phase` | 已有历史公开身份；attempt为正整数或null，phase复用现有枚举 |
| `inspection_state` | verified/unknown/invalid；verified仅原登记进程事实符合本合同 |
| `prepared_record_count`、`registered_terminal_count`、`direct_exit_count`、`descendant_domain_count` | 非负int或null；可核实计数才给整数，未知不冒充0 |
| `coverage_complete` | bool；该原 attempt 引用完整核查，非金融 stopped proof |
| `reason_codes` | 最多12个固定原因；显示未登记/缺终止引用/绑定冲突/文件缺失/截断等 |

建议最小固定原因：`context_invalid`、`index_invalid`、`attempt_unregistered`、`binding_invalid`、`terminal_refs_missing`、`terminal_refs_conflict`、`fact_missing`、`fact_invalid`、`directory_extra`、`scan_truncated`、`budget_exceeded`、`identity_unconfirmed`；global另有`non_effect_unanchored`、`investigation_unanchored`。不返回 path/PID/host/namespace、原 worker/owner、脚本参数或事实正文。不提供 all_workflow_stopped、free、allowed 或恢复/解除能力。

## 3. 真正可实现的原绑定与终止引用

先沿现有 `_state` 验证 index，沿 `_prepared_process_refs` 验证现有严格8字段 prepared refs；使用**原条目**而非当前 claim。原 prepared expected 只比较真实 fact 有的字段：

`schema_version`、`record_id`、`workflow_id`、`action_id`、`action_name="ar_"+entry.phase`、`attempt`、`worker_id`、`reconciliation_date`、`skill_hash`、`material_set_id`、`material_version`、`plan_fingerprint`、`script`、`script_sha256`、`arguments_sha256`。

前三类来源分别为固定 evidence schema/ref identity、原 entry、原 prepared ref；全部**类型和值**严格一致。safety 的 owner_id/department_id/skill_id/workspace_sha256 并不存在于 prepared fact，不能要求 fact 凭空包含它们；它们仍由 index 原 binding digest 验证。旧材料/计划不与最新 context 硬比。当前 claim 的 worker/attempt 不替换旧值；已有 metadata 报身份/计数冲突时保守 unknown/invalid。

终止引用只取原持久化 `WorkflowAction.result_json` 或仍留存 `ar_failure.process_records`。真实 payload 没有顶层 attempt/worker：必须用 `record_id+prepared_sha256` 与原登记 refs 桥接，再检查每个 started/exited 的原 BINDING_FIELDS 类型和值，以及 domain receipt 原 token/监督进程身份。成功 result 可进一步与该原 completed entry.result_sha256 对比；失败 payload 只读原 action_id/phase，不能拿当前 action_count 猜其 attempt。不把一个不匹配的候选选作“最新”覆盖。

旧 terminal refs 已丢失则 unknown；即使文件还在，也不得扫描计算 terminal hash制造原注册。只可按已有登记指纹读取事实；直接 exit、Linux后代域、当前存活观察分开，PID不在或 lease过期不代表停止。外部服务、金融结果、材料占用和恢复资格始终不由本片段证明。F1旧 inspector/恢复及 F4.B gate 不改。

## 4. 可实施预算与完整性

现有 index最多128 attempts；prepared_refs最多128/同action、全index理论可至16384 refs。**全请求128 records是新只读检查预算，不是现有数据不变量**；超过即 partial/unknown，不改写或拒绝原合法登记。F4.A2048详细action/256输出也不是 SQL预加载/wholeGET预算。

建议固定新文件核查预算：最多128 registered records、512 facts，每 fact最多16KiB，成功读取原事实累计最多8MiB；读取大小越界所需的单字节哨兵另有固定界限，首次越界即停止。仅处理现有 payload：每个原 terminal JSON最多128KiB、累计最多2MiB，先字符串长度检查再有界编码/解析；超限保留 unknown。以上不界定既有 ORM已加载字符串/关系或 API原检查成本。

根/动作/record目录枚举采用统一最多1024个目录项（允许第1025项仅判截断），计入无关、非法及extra项；record总上限128，超过不继续事实读取。按受控root和原action安全定位；原action所有已登记attempt的 record_id并集与目录比对，旧合法attempt不是extra。目录缺失、未登记目录、symlink/非法内容均显式报告；未扫描部分不能判missing。已登记的未检查facts是“预算未核查”，不能说已验证。

任何目录/事实/terminal来源数量截断都使registered_effect_coverage_complete=false；whole_workflow始终unknown。0 refs只表无完整注册，不推未启动。只读观察可能看到写入中的证据而得到unknown，允许显式再查询，不启动调查。无硬墙钟保证、不发送信号、不产生进程、不写 DB/Audit/ref；文件系统只读和有限身份观察。

## 5. 首个集成 red 与完成标准

**首 red**：隔离真实 ORM/PG workflow+同一action两个真实登记attempt，用固定快照 benign no-op 实际 recorded helper+原gate生成prepared/启动/退出事实；fixture按现有合同构建original index。attempt1旧terminalpayload已覆盖，attempt2 terminal payload仍留存；真实原journal含两次记录。opt-in public `read_execution` 应按原worker/attempt核prepared1并显示terminal unknown，按原refs核attempt2；不得把attempt1目录当extra，不得把当前claim套到attempt1。默认false原response/恢复结论不变，全workflowunknown。合成claim迁移只是隔离证据场景，绝不重跑真实金融writer。

完成标准仅：

1. 首 red→最小实现→green；补原terminal来源阳性、绑定类型冲突、extra/missing/非法路径、预算截断和legacy/unavailable核心反例。
2. defaultfalse不调用新inspector；true沿同GET/BFF权限链，原所有POST/轮询保持false；无DML/Audit/Popen/信号，原fingerprint/allowed不变。
3. JSON/TS正式生成并check，旧响应无字段可读；实际只读UI按需显示unknown/过期/错误，无新业务按钮。
4. 独立Spec/Standards审查、必要构建、上线runtimehash/health和实际浏览器只读验收分别记录。未完成项不宣称通过。

整个F4还缺non-effect/独立调查锚定、不可变terminal引用、多attempt全域调查/条件审计处置；本片段不提前实现或改变这些授权合同。


## 6. Root implementation decisions and count semantics

The existing history DTO remains unchanged. The independent read-model module owns typed DTOs, file/identity reads and fixed public reason codes. Runtime details are for observation only. Keep the existing F1 inspector, recovery checkpoint/admission/material occupancy, F4.B launch gate and effect registration unchanged.

Success terminal payload provenance requires its canonical digest to match the original phase_completed entry.result_sha256. Failure payload must have exact original action_id/phase and its complete reference set uniquely bridge to one original attempt through record_id+prepared_sha256+script; a mixed-attempt, duplicate, malformed or conflicting source is not selected as the latest substitute. Validate original facts against original bindings using both type and value. No absent payload attempt/worker fields are invented.

prepared_record_count counts registered original prepared refs; it does not claim each prepared file has been validated. registered_terminal_count counts uniquely attributable references containing required original started/exit fingerprints (and domain fingerprint for a recorded modern Linux domain). direct_exit_count and descendant_domain_count count facts actually validated. If provenance is missing/ambiguous or a scan is truncated, unavailable quantities are null, rather than zero. A known zero is displayed as a count of registered/verified facts, never as no launch/no process. prepared_refs_missing is an additional fixed reason for a registered attempt without anchors; attempt_unregistered is reserved for legacy metadata gaps. coverage_complete/verified require complete valid registered-reference reads; they are not financial stop/no_effect proofs.

Add an optional per-item fixed liveness map (running/not_running/exited_unreaped/identity_changed/different_scope/not_recorded/unavailable counts) only if actually observed, no raw identity. The API and Worker may differ in process namespace. different_scope must not be rendered as no running process, and a valid original subreaper receipt is not invalidated just because the optional current identity probe cannot query the same space. Running identity conflicting with an exit receipt remains invalid; incomplete legacy direct proof remains explicit. whole_workflow_coverage is always unknown in this stage.

New file reads use a controlled no-symlink directory/regular-file boundary, including parent-directory traversal; do not modify the legacy inspector merely to reuse its path reader. Directory and file budgets include every scanned entry and missing/invalid attempt, not just matches. Record contents are never returned. JSON payload byte limits bound new parsing/encoding, not the already-loaded ORM strings.

Frontend completion requires a distinct details state, explicit GET only, cancellation on close/workflow or metadata/progress changes, protection against out-of-order results, a visible stale/error/unknown result and no new business mutation. A details response whose metadata_snapshot_fingerprint differs from current history is rejected as stale. Original default response and action buttons retain their authority. Formal OpenAPI export and locked TS generation must precede typed UI edits; no hand-edit of generated files.

First red must go through real read_execution after actual no-op/gate preparation of two original attempts. If the existing function rejects the new keyword, report that exact integration-entry failure and do not claim subsequent assertions ran. Proceed one red/green slice at a time. The final acceptance matrix uses no real financial script or business workbook parsing/writing, no production mutation or Git commit/push. Root owns release and read-only browser acceptance; test and implementation ownership remain separate.
