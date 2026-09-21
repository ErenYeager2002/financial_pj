# PR-04 停用账号 Workflow 管理员停止：已核实缺口

依据 execution-guide.md PR-04 第7项：账号停用无法登录时，管理员必须能够受审计地停止，不扩大跨部门权限。当前 pi_admin_session_service.stop_disabled_owner_session 已实现同部门当前管理员、当前 owner disabled 及审计；Workflow 尚缺对应能力。

当前证据：cancel_workflow_batch 和 _request_workflow_cancellation 都刷新当前实际 actor、检查固定 department 后，明确拒绝 owner_id != actor.user_id；cancel_workflow 复用该限制。不能构造 owner 的 UserContext 绕过，因为真实操作者及审计会失真。普通发起人取消的既有授权应继续保留。

实施边界：独立管理员入口，调度锁后同时刷新实际管理员、目标任务与 owner；仅同部门已停用 owner 可用，部门变更、管理员降权、owner 重新启用均拒绝。复用现有取消状态迁移，保持多日期整批取消和原子写/发布登记保护；不新增强制 kill，不自动重跑。审计必须记录实际管理员、原 owner、停用原因和结果，状态与审计同一事务。终态幂等响应不能谎称已停止仍活跃调查任务。

验证：单日/批次、排队/正在读取/原子写保护、已结束幂等、实际管理员降权、跨部门、账号重新启用、审计失败回滚、匿名HTTP拒绝、普通发起人撤权后取消仍有效。已核实 cancel_investigation 不自行授权或提交，只标记取消并以传入 actor 审计；授权必须由调用入口承担。终态 Workflow 仍有调查动作时必须覆盖这条分支，不能仅处理普通 queued/running 状态。

尚未实现或部署此入口。当前源码与线上取数确认修复保持不变；本记录用于下一实施切片。

后续实施已上线，见PR-04-workflow-admin-stop.md与runtime-verified.json；锁等待期间账号恢复/换部门的专项并发组合仍待补齐。
