# PR-04 审批决定当前身份与并发保护

已确认：approval_service.list_approvals 和 decide_approval 直接检查传入 actor.is_admin；路由的 require_admin 发生于请求依赖解析后，服务未等待统一 mutation lock 后刷新身份。decide_approval 的 db.get 不刷新既有 identity map，也未序列化并发审批；list_approvals 的读取还会使过期审批变更并提交。

本轮范围：管理员服务入口先获得 scheduler global，再 refresh_active_user/require_admin；审批与工作流读取刷新当前记录；只有当前仍等待审批的任务可批准，批准前复核原所有者当前身份和 Skill 执行权限。拒绝审批属于停止推进行为，不要求原所有者保有运行权限。保持请求方不能自批、同部门隔离、快照复核、审计和一次决定。

使用独立 PostgreSQL 合成数据覆盖管理员降权/停用/换部门、已撤销审批/取消工作流/停用所有者、实际锁等待、合法决定及重复决定。审批证据固定为合成摘要，故该套件不证明财务文件内容核验，也不执行核销。

现有服务内提交语义本轮保持；到全事务重构阶段须继续按调用链明确。写入批准不表示跨外部系统具备瞬时撤权；Worker 仍须在实际步骤前核验。当前未部署。
