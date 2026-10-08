# F2：普通 Run 按当前容量公平领取

Status: ready-for-agent
Date: 2026-10-08

## 目标与范围

修复普通 `Run` 最前 100 条均达到 Skill 并发上限时，第 101 条独立可执行任务永久不可见的问题。依据用户提供的《financial_platform_pi_construction_standard_v1_2026-09-23.md》§12.3、§12.4 及 A24；操作遵守项目 AGENTS.md。使用容量 SQL 预过滤及现有单次 100 候选上限；不分页、不保留跨 loop 游标、不新增表或字段。

本规格仅为 F2/A24。A25 维护最大延后、F3 统一重试、多 attempt 调查、发布崩溃矩阵另行完成；不将此补丁视为 CW07 全部完成。保留 F1 完整 Linux 后代域封存规则、AR balance.37、原财务材料及占用规则。

## 单一领取规则

领取事务沿用：global scheduler lock → recover_expired_jobs → flush → 候选 query → 原检查 → running/event/StepRun → 单次 commit。持锁期间最多加载并检查 100 个候选，最多领取一个；不提前 commit，不改锁顺序和锁种类。

候选查询以 queued 且 pool 属于当前 Worker 为条件，从整个队列选出当前仍有并发容量的任务，再按既有优先顺序取前 100。容量来自 grouped active-count 子查询：

- 按 skill_id 分组，统计所有 owner、department、pool 的 state=running。
- active 仅使用原 active_run_count 口径：lease_expires_at 为 NULL，或大于等于本次 now；NULL 代表 unknown 占用，仍计入。
- 恢复修改先 flush、不 commit；过期普通 Run 转为 NULL lease 后仍占用。
- 每个 queued Run 逐行比较 active_count < CASE WHEN concurrency_limit < 1 THEN 1 ELSE concurrency_limit END；无 running 分组时 active_count=0。
- 比较的是该 Run 创建时固定的 concurrency_limit，不读取当前 Skill manifest，不把整个 Skill 一刀切排除。active=1 时，同 Skill 的 limit1 旧任务跳过，limit2 任务仍可候选；这是原有上限语义。

排序显式使用 queued_at ASC NULLS LAST、created_at ASC、id ASC。queued_at 可空，id 决胜使同时间任务确定；保持生产 PostgreSQL 原 NULL-last 语义，使 SQLite 验证一致。一次候选列表即可，不引入 keyset 或 OFFSET。

逐个重新读取候选后确认仍为 queued 且 pool 匹配。保留原 manifest 校验、active_run_count 锁内复核、execution_owner(CLAIM)、assert_run_confirmation、assert_execution_snapshot、拒绝事件、running 属性、attempt/heartbeat/lease、领取事件及 StepRun。容量 SQL 仅缩小候选集合，不授予执行权限。执行适配器与 START、发布、完成登记的检查保持原流程。

正常循环唯一原地保持 queued 的业务 skip 是并发已满。SQL 排除这些行后，候选会被领取，或因原校验明确 failed 并离开 queued。因此本轮 100 个候选全部被拒绝并 commit 后，下一轮从剩余队列重新查询即可前进。系统异常或 commit 失败必须回滚并暴露故障，不为了推进而吞错或跳过未知事实。

## 行为变化

权限、确认与固定快照检查原本位于并发判断之后，因此满额时这些失效任务此前也不会清理，新查询保留其时机。有容量时仍按原规则拒绝，attempt 保持 0。

唯一可见变化：原逻辑先验证 manifest 再检查容量，满额 Skill 的坏 manifest 可提前 failed；新预过滤会在容量恢复后再给出坏 manifest 失败提示。接受这项提示时机变化，执行准入不变。测试与交付需明确说明，不宣称所有行为完全不变。

## 候选查询预算与错误

候选检查上限保持 100，不把 100 改大。PostgreSQL 候选 SELECT 单独使用事务局部 statement_timeout，最多 2s，保留已有更严格的非 0 限额：读取原值、set_config(..., true)、完整消费候选列表、成功后恢复原值再进入检查。其他恢复、授权、事件、StepRun 或 commit 不受这项新增 2s 上限影响，沿用原配置。

候选 SQL 失败或超时不返回空列表、不解释为无可执行任务。PostgreSQL 事务进入失败状态后应传播原错误并整体 rollback，事务局部设置随回滚恢复；不得在已失败事务里用恢复 SET 的二次异常遮蔽原错误。非 PostgreSQL 不发送 PostgreSQL 设置语句。全局 lock timeout 与锁等待行为沿用现有值。

LIMIT 100 只限制加载及应用检查数量，不证明数据库扫描成本恒定。隔离 PostgreSQL 检查 grouped counts 查询计划和 2s 行为；如查询失败，应保留失败证据而不是扩大预算或削弱条件。当前补丁不默认新增索引迁移。

## 聚合观测

记录候选 SELECT 耗时、整次领取耗时、checked_count<=100、invalid_snapshot_count、claim_denied_count、容量复核 skip 数及结果原因。原因至少区分 selected、candidate_budget_reached、no_capacity_eligible_candidate、candidate_query_timeout/error、claim_error。达到 100 不能未经额外查询宣称队列仍有剩余，只记录预算达到。

观测采用服务端聚合日志和可测试的观测结果；仅白名单计数、耗时、原因及固定操作名称，包含池名时限于服务端配置的 pool。日志无 Run/owner/Skill 等标识、姓名、文件名、金额、财务内容、SQL参数或异常原文；SQLSTATE/异常类可作为固定错误分类。常规 idle/no_capacity_eligible_candidate 不连续输出日志；有检查、领取、拒绝或失败时记录。不得给饱和任务逐轮追加 RunEvent。

## 验证与完成条件

隔离 PostgreSQL 使用真实 global lock、真实计数及 claim，固定假只读 Skill/用户/权限/快照，调用领取但不运行适配器、不执行核销、不写生产材料：

1. 前100为满额 Skill A，第101为独立 B；一次领取 B，A 仍 queued、attempt0，无新增任务事件。
2. 同 Skill 不同 Run 的 limit1/limit2，active=1；仅 limit2 可以候选。所有 pool/owner 的活动均计入。
3. NULL lease unknown 与 recovery 后的 NULL lease 仍阻止同 Skill；独立 Skill 不受遮挡。
4. 前100个有容量但被权限/确认/固定快照拒绝，后有 B；首轮准确 failed、attempt0，commit后第二轮领取 B。保持原拒绝合同。
5. 两个独立 Session 竞争唯一 B，真实 global lock 等待后仅一次 attempt/领取；上限2的三个候选不得超过两条 running。
6. 同 queued_at/created_at 与 NULL queued_at 排序确定；所有候选加载及检查最多100。
7. 已满额坏 manifest 延后失败；有容量坏 manifest 按原规则失败，不启动适配器。
8. PostgreSQL候选超时或查询错误传播并回滚，不能返回 empty；原 statement_timeout 在成功/失败后恢复，候选query以外不被新增2s设置影响。commit失败不留下部分领取或拒绝事实。
9. 聚合观测记录正确计数/耗时/原因，无标识及财务内容；反复 idle 不产生噪音日志。

先针对性 red/green、静态 diff 审查、适用类型/编译检查、双轴审查；全量与无关测试不自动执行。部署按 AGENTS.md 当前持续授权由根代理完成：保留现有独立修改、当前回滚配置与活动任务，排空后更新必要服务，回读 API/相关 Worker 源码哈希及健康，浏览器只读验收。未测试、未上线的阶段分别报告，不以规格落盘冒充完成。

## 实施入口

先读取 [01-capacity-eligible-claim](issues/01-capacity-eligible-claim.md)。生产入口为远程持久化 backend/app/worker.py 与 scheduler.py 的现有计数规则；本轮规格写入不改变这些产品文件。当前 F1 发布依据 docs/ar-cw06-abandonment-scope-20261008.md 及根代理现场 readback；旧上下文不作为当前镜像或活动任务授权。


## Completion 2026-10-08

F2 source, targeted verification, production deployment and read-only browser acceptance completed; see [release evidence](../../../docs/pi-cw07-run-claim-capacity-20261008.md). No commit, push or financial task. Overall construction continues with F4.A.
