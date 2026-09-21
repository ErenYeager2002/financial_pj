# PR-04 材料相关入口审查（尚未全部修改）

当前源码核查发现：

- reset_workflow 的旧缓存和实际 actor 缺口已修复，165项专项通过；本轮发布/回读证据见PR-04-reset-boundary.md。
- request_fetched_data_supplement 仅接收工作流与业务参数，没有实际 actor 参数；单日/批次 HTTP 在服务外检查，不能保证锁后身份。批次包装同样缺 actor。需要同时修改服务签名、两个路由及批次包装，不能用 owner 代替实际操作者。
- confirm_fetched_data_review 同时供 HTTP、Pi Harness 与 Worker 自动确认使用。目前 owner 检查发生在 Workflow 行锁前，实际 actor 未刷新；Harness 检查也早于任务刷新。不能直接在函数中新增提交或盲目改变锁顺序，因为 automatic=True 的分支参与 Worker 外层完成事务。
- 自动确认的 fetch_data、build_fetch_preview、supplement_fetched_data 等调用链在返回结果后获取 scheduler 锁或通过 lock_execution 获取它；仍需逐分支核实，不以几个调用点推定全部安全。
- 手工取数确认/补取服务内已有提交，HTTP 随后使用原 user 另行写审计。补强时应同时保证实际 actor 审计与操作事务一致，不能只补服务检查却继续记录旧角色。

这份记录是剩余工作证据，不代表以上材料入口已经修复、部署或业务验收。未执行真实取数、补取、确认或核销。


补取后续处理：两个公开入口已接入实际actor、锁后刷新及同事务审计；私有准备函数不提交，HTTP不再另行审计。180项专项通过，部署状态见PR-04-supplement-boundary.md。上方补取问题描述作为发现时记录，当前剩余为confirm_fetched_data_review及其手工/自动/批次调用边界。

## 取数确认调用链复核（2026-09-20，实施前）

本轮按当前源码追踪四个生产调用点，结构证据与源码 SHA-256 见 PR-04-confirmation-transaction-audit.json。

1. confirm_bundle 仅 flush，不提交；事务割裂发生在 confirm_fetched_data_review 的两个人工分支（空日与普通日），不是取数包服务。HTTP 单日、批次及 Pi accept_fetched_data 都在核心函数返回后追加审计并提交，审计异常无法撤销此前已提交的确认。
2. 自动确认不能增加提交：execute_workflow_action 在确认后才设置当前动作 succeeded/result/finished_at。确认和当前动作完成必须由外层提交。prepare_workspace 的旧取数结果通过 _transition_legacy_fetch_result 提交并获得 scheduler 锁；prepare_worklist 同样提交后获得该锁；build_fetch_preview 使用 lock_execution；supplement_fetched_data 提交后获得 scheduler 锁。不能只检查 fetch_data 分支后推定全部调用安全。
3. Pi reserve_agent_call 在新版预算记录更新后主动提交，旧版直接返回；因此即使预算校验中曾获得 scheduler 锁，queue_pi_harness_tool 也不能假定仍持有该锁。请求入口的 _assert_active_harness 本身不校验到期时间。后续确认前必须重新校验同一 action_id、worker_id、状态和期限，不能仅以任一 running Harness 动作存在为准。
4. 人工确认必须在 scheduler 锁及任务刷新后重新核验实际 actor 和任务 owner，再检查执行方式。批次还需刷新子任务关系并对选中子任务授权，不能在旧关系上确认。
5. confirm_bundle 按 actor.user_id 查找归属包。不能为了支持管理员而静默替换 actor 为 owner；保留当前归属约束，管理员处理策略须与既有权限契约一致，审计始终记录实际操作者。

实施边界：共用核心不提交；人工入口负责实际 actor 审计与一次提交，Pi 入口重新核验租约并同事务审计，Worker 保留外层事务。需要新增真实数据库的审计失败回滚、等待锁期间身份/阶段变化、空日、重复确认及自动确认外层回滚验证；旧测试以 SimpleNamespace(user_id) 模拟身份，不能作为完整授权测试。

这次完成调用链与事务责任核验，尚未修改确认实现或发布该修复。线上保持已合并的 6940bdbe8edb；没有确认真实任务或执行财务写入。

后续实施：上述取数确认切片已修复并上线，证据见 PR-04-fetched-confirmation.md；完整 Worker 外层回滚验收仍待补齐。
