# PR-04 直接 Agent 动作的身份与阶段边界

## 本轮问题与修改

直接 apply_workflow_agent_action 服务此前只重新读取任务 owner 的资格，实际 actor 和 WorkflowSession 阶段可能来自请求早期缓存。四个新增用例证实旧管理员身份、其他用户、跨部门管理员及缓存旧阶段会通过服务入口。HTTP 路由有早期归属检查，但不能替代服务内当前状态边界。

backend/app/workflow_service.py 现在取得 scheduler 锁，刷新任务，再复用 execution_actor(CONFIRM) 核对当前实际用户、固定部门、归属和 Skill 权限；随后才检查后台 Harness、owner、部署门禁及允许动作。该直接入口不调用 LLM。取消及重建在自身提交/重新加锁后继续执行其专用校验。

## 验证

backend/tests/test_execution_authorization.py 增加九项真实数据库用例，旧代码四项失败。合法 owner 和同部门管理员仍可修改日期；拒绝分支不修改日期或创建消息。现有后台、日期与 Agent API 兼容测试加入 scripts/refactor/check.py 的专项套件。

两个既有 FakeDb 状态机单元测试仅模拟新增基础设施边界，保留业务断言；身份与锁行为由真实 PostgreSQL 用例覆盖。137 项专项与接口兼容测试通过，静态 diff 检查通过。候选及受限恢复镜像的隔离 PG 迁移、重复迁移、只读角色与事务检查通过，213 个 AR Skill 文件哈希保持。

## 发布边界

构建基础为线上 0a0c0d2b6127，候选 8936841ccc9a，受限恢复 ced5b1c92931。预检 normal、五类活动计数零，未发现并行版本变化。运行生效须看 PR-04-agent-actor-deployment.json 与 PR-04-agent-actor-runtime-verified.json。

无数据库结构变更，无真实财务执行或恢复，无提交推送；看板无操作。PR-04 仍未完成所有入口及阶段矩阵，聊天模型决策路径等继续核查，不能把本次直接 Agent 校验视为全路径完成。

双轴只读审查通过。当前直接 Agent 白名单不含取消；先前对 Agent cancel 分支的模拟只能证明内部防御逻辑，不能算当前公开接口的取消验收。公开取消与聊天取消分别由其真实入口测试覆盖。

2026-09-20 06:20 UTC 发布与运行回读完成：API 和两个 Worker 均为 8936841ccc9a，各 199 后端及 213 AR 文件哈希一致，UID10001、restart0、DB唯一f3、replay-only=false；mode/public normal，五类活动计数零。
