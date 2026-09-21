# PR-04 真实入口与剩余授权边界核对

核对版本：线上 a2058278611f，远程持久化源码同版本后仅新增合成测试与文档。

## 审批入口可达性

静态全 backend/app 扫描发现 request_workflow_approval 与 assert_workflow_action_approval 只有函数定义，没有调用。不能用这些遗留 helper 的存在声称当前 Worker 执行了双人审批。现有管理员 list/decision 路由真实可达，上一切片已覆盖其身份与并发决定。当前 confirm_workflow_result 经 send_workflow_message 执行；必须继续沿这个实际链路及新版 AR 14 阶段检查，不能只修未调用 helper。

## 取消后的已发布登记

最初单看 execute_phase 中 state=cancelling 的拒绝条件，怀疑它阻断 complete_reconciliation。继续读取 _request_workflow_cancellation 后已排除正常入口的这一推断：有已发布但缺正式台账的任务会保留 state=running，设置 stop_after_action；批次取消同样保持当前任务状态，并取消剩余日期。transition_phase 还专门保留必要完成阶段，script 对完成脚本有停止标记例外。

新增 test_ar_published_cancellation.py 在隔离 PostgreSQL 中用真实 cancel 服务覆盖单任务/批次、queued/running 完成动作。断言当前任务仍运行、停止标记和发布事实保留、无新增动作、剩余日期取消。只验证取消状态转换，不证明实际台账脚本运行、发布文件内容或最终批次终态。

## 仍未完成的 PR-04 要求

| 要求 | 当前依据 | 尚需工作 |
| --- | --- | --- |
| 当前所有者和固定部门 | workflow_owner_context 刷新User，核验部门和Skill权限；ArExecution.verify_input_binding与派发使用该入口 | 为14阶段实际入口补齐撤权/停用/部门变化的矩阵证据 |
| 原子动作后必要收尾 | 取消路径已显式保留已发布登记；不可粗暴终止已开始脚本 | 用户被停用/撤权时，claim及verify_input_binding仍执行普通权限检查；必须核定必要收尾授权边界，不能直接删除检查放行全部动作 |
| 写入材料和固定版本 | verify_input_binding比较当前材料id/version、日期和skill_hash，暂存/计划/发布另有指纹核验 | 完整API→Agent→Worker矩阵，以及外部状态变化的回归证据 |
| 授权观察版本 | 普通Run的execution_owner(observe=True)记录授权事实摘要 | workflow_owner_context目前不记录同等观察摘要；仍缺Workflow/AR/Pi阶段对应记录 |
| 事务与锁 | AR lock_execution在阶段和脚本前刷新租约/任务并持global，发布保持同事务 | lock_execution含db.commit的前置约定需要沿所有调用点核验，不把注释当作无待提交写入的证明 |

该核对没有修改财务执行逻辑、没有重跑真实任务、没有操作看板。PR-04 不标为完成，PR-05～PR-21 范围保持不变。
