# F4.A：各次执行的只读元数据

Status: ready-for-agent
Date: 2026-10-08

## 范围与现有 seam

按用户施工规范 §10.3、§10.7、§11.7 推进完整 F4。此阶段复用现有 ArExecutionRead/read_execution 和 workflow execution GET，加显式 attempt_history DTO及历史记录界面；不新建endpoint、表、权限或占用台账。保存原不可变 index绑定，不让最后成功覆盖较早未知。此阶段只完成元数据查询，不冒充已调查全部进程、财务效果或已实现管理员解除。完整F4随后继续。

基线：Git6476660、线上backend85bb307、frontendcfd960；ar_execution_service57d812277a6093fb2272bd79ef6820f05b141ff60d92fe763e8bd0059eb06236，safety003381ed4028bad3465269f12c3b26923bea3b1e308a2e5364e169030165f5dd。现场hash与已有diff必须再核实。

## 明确返回合同

ArExecutionRead新增可选 attempt_history: ArAttemptHistoryRead（旧响应不存在时UI容忍）。新DTO定义在纯读取模块 ar_attempt_history.py。三条已有execution GET/recover/investigate响应共用模型，不执行POST验收。

ArAttemptHistoryRead字段：schema_version固定ar-attempt-history-metadata-v1；metadata_coverage_complete bool；process_evidence_checked固定false；authorizes_resume固定false；evidence_revision int|null；snapshot_fingerprint SHA256；registered_attempt_count 0..128；missing_attempt_count 非负int|null；scanned_action_count 0..2048；items最长256；reason_codes最多16个固定code。字段内计数仅指已扫描metadata，不声称完整业务/SQL扫描。

ArAttemptHistoryItem字段：action_id经验证的opaque UUID（不回显任意非法字符串）；attempt 正int|null；phase限定write_ledger/write_receipt_flow/publish_reconciliation/complete_reconciliation；record_state限定intent_recorded/phase_completed/legacy_unknown；binding_sha256 SHA256或空；material_version 正int|null；intent_at/completed_at经验证的datetime|null；missing_attempt_count 非负int|null；reason_codes最多8个固定code。无Worker/owner/department/Skill/材料ID、路径、PID、host、原refs、输入结果错误原文、单据/金额或任意额外context字段。

phase_completed只表示该次阶段完成事实已登记，不代表停止、发布、余额或解除。process_evidence_checked=false和authorizes_resume=false适用于整个history投影；原合法recovery_allowed等原字段保持原规则，历史展示本身不授予执行权限。snapshot_fingerprint仅变化检测摘要，不是授权凭据。

## 集合、缺口和边界

- 先用既有_state(context,workflow.id)校验完整index及绑定；128上限、重复、错误schema/revision/字段、foreign workflow和摘要不一致明确覆盖不完整。非法index不回传未核验原记录。revision未知用null，不能默认0掩盖缺失。
- 有效index每(action_id,attempt)保留原record_state/binding/material_version/时间；同action attempt1 intent+attempt2完成仍展示两条，不能复制当前action状态/worker覆盖旧事实。index存在但action缺失仍展示原记录，增加固定缺口原因和coverage=false。
- 仅扫描已有WorkflowAction中四个effect phase。正常未开始queued/counter0不假造历史；有启动迹象而无完整index、counter无效/冲突、current action与index阶段/身份矛盾都显式未知。
- 不按range(attempt_count)生成历史。某action已登记attempt数少于有效counter时，仅补一条legacy_unknown/attempt=null缺口；missing_attempt_count来自可信非负counter与已登记集合，counter/绑定冲突用null，不clamp、不猜worker/材料/单次结局。
- 动作详细metadata投影最多2048（包括非effect动作；历史条目仅来自四个effect phase），输出最多256。为避免ORM返回顺序造成不同抽样，从既有已加载actions按稳定身份键以heapq.nsmallest选2049项，再检查2048项详细metadata并用多一项识别截断。身份选择遍历全部已加载集合，O(n)选择成本、O(2049)额外内存；本上限不代表SQL预加载、全部身份遍历或整个GET成本有界。任何截断reason_codes明确、coverage=false，不能把未扫部分说成0。非法/巨大counter不展开；缺失计数无法完整核实时null。
- 排序稳定，优先保留有效已登记原记录，再列未登记缺口；同集合重复读取fingerprint一致，不依赖请求时间。摘要仅针对本次已读取context/index、稳定选中动作的详细元数据及截断标记；范围内变化应改变摘要，未纳入详细投影的动作字段变化不保证改变摘要。仅输出固定原因，不回显畸形字段。此partial fingerprint不可作为后续管理员解除凭据；后续条件处置必须验证完整原证据快照。
- 无JSON/非object context不500：history返回明确context_invalid、coverage=false，整体available=false、原默认执行controls关闭。unsupported ar_execution schema保留available=false，同时可读合法history；有效legacy其他原行为不变。无历史的旧响应/任务可正常展示空记录，不误称全部进程停止。

## 实施与验证

生产仅新pure投影模块、ar_execution_service最小接线、现有workflow-execution-results界面和必要JSON/generated TS。不改safety/admission/恢复/封存/发布业务规则。使用现有export_openapi.py及openapi-typescript生成；冻结旧契约缺F1 abandon的差异并明确归属，不丢路由或手写DTO。

第一条red从真实read_execution seam建立同action两次原意图/完成事实；无mock guard。逐slice补：缺index/较早缺口/orphan、坏context/index/计数、128/129及2048/256边界、脱敏、排序/fingerprint、读前后对象/DB无DML/commit、原占用保持、旧available/原执行状态兼容。只跑针对性文件和相关contract/typecheck/build，不默认全量，不跑真实核销。

双轴静态审查通过后，由root按持续授权受控上线必要backend与frontend，保留F1/F2/balance.37及已存在差异/活动任务、回滚配置。读回源码/三后端/前端hash，API健康及normal；真实登录只GET及展示，不恢复/调查/解除/重跑。缺历史行明确未知，阶段完成不标成进程退出；浏览器验收通过再进入F4后续。


## Comments

F4.A completed 2026-10-08: source, targeted validation, deployment and read-only browser acceptance. See [checkpoint](../../docs/pi-cw06-attempt-history-20261008.md). This closes only this implementation scope; overall construction remains active with F4.B next.
