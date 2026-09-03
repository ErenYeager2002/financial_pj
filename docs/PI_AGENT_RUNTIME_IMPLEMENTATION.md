# Pi Agent Runtime 实施说明

## 应收核销后台执行

应收核销现在支持 `workflow` 与 `pi_harness` 两种任务级执行方式。前者沿用固定 Workflow；后者由独立 Agent Worker 读取任务创建时固定的完整 `SKILL.md` 和 Skill 自带工具清单，逐步请求受控 Python Worker 执行。任务创建后不能切换执行方式，也不会在两种方式之间自动回退。

后台 Agent Worker 需要与 FastAPI 共同配置独立的 `FINANCIAL_PI_HARNESS_TOKEN`。该令牌只用于内部 Worker 认证，不得复用数据库密码、Clerk 密钥或模型密钥。开发启动脚本会在本机开发配置缺失时生成随机值；生产配置生成脚本会生成并限制配置文件 ACL。

Pi Harness 会收到任务记录中保存的完整业务上下文，包括输入材料元数据、工作区路径、取数与核销汇总、产物、消息、动作输入输出和多日批次状态，并可通过 `inspect_fetched_data` 分页读取当前核销日的全部 AR、订单、核销和异常明细，通过 `read_task_file` 分页读取任务目录中的结构化文本资料。认证字段在进入模型前递归过滤；智云密码、平台内部令牌、模型密钥和会话认证信息不会作为任务上下文发送。写入请求必须携带任务返回的核销日期、材料版本、计划指纹，并再次通过所属账号的 Skill 权限校验。写入仍由原有暂存和回读机制完成，失败后不会自动重试。

## 范围

平台把 Pi 作为服务端 Agent Runtime 使用。Pi 只负责会话、模型流式响应和受控工具调用；身份认证、Skill 权限、模型连接、任务草稿、工作流阶段和 Worker 执行仍由平台后端负责。

标准 AI 助手使用 `web/src/features/ai-chat/agent-server.ts`，工作流 Agent 使用 `web/src/features/workflow-agent/server.ts`。二者都通过 Next.js 服务端 BFF 调用 FastAPI，不把 Clerk Bearer、模型密钥、数据库连接或本地路径发送到浏览器。

网页入口是 `/dashboard/ai-chat` 和 `/dashboard/workflows`。AI 助手恢复为可连续对话的聊天框，
可调用模型并查询当前用户可见的运行任务；工作流页面可以创建受控会话、查看阶段和进度、向
Agent 发送请求，并用页面确认按钮把发起人的写入确认交给原有状态机；创建会话不会直接启动 Worker。

## 工作流 Agent 边界

工作流 Agent 当前只允许以下五类动作：查询阶段、设置核销日期、请求准备日清、请求重新生成、请求用户确认。FastAPI 会再次按工作流阶段和参数校验动作；准备和重新生成只会排队现有 Workflow Worker，不能从 Agent 进程直接启动脚本。任务不再等待管理员审批，写入型工作流只保留发起人的写入确认和变更复核。

工作流模型连接 ID 只从受认证的 `/api/workflows/{workflow_id}/agent/context` 返回给服务端 BFF，普通工作流响应不包含该字段。模型网关会重新校验连接归属、部门和模型名称，并只记录状态、耗时和 Token 统计，不记录消息正文。

## 灰度配置

生产 Compose 默认使用 Pi：

```text
AGENT_RUNTIME=pi
AGENT_RUNTIME_PI_USERS=
AGENT_RUNTIME_FALLBACK=legacy
```

只有需要灰度旧实现时才设置 `AGENT_RUNTIME=legacy`；此时把测试账号的 Clerk User ID 写入
`AGENT_RUNTIME_PI_USERS`，多个 ID 用英文逗号分隔，这些账号使用 Pi，其余账号使用旧实现。
Next.js 服务端优先使用 Clerk `userId` 做选择，只有 Clerk 身份不可用时才使用平台用户 ID。
未知配置按旧实现处理。

开启回退时，Pi 只有在尚未产生文本或业务工具事件就失败的情况下才会调用旧实现；已经调用工具的会话只返回错误，不会重复执行。

本阶段对 `ar-hexiao-daily` 的工作流 Agent 也阻断旧实现回退，避免模型网关故障时误进入旧对话执行路径；该 Skill 仅保留合成数据和只读检查。

生产 Compose 还设置 `FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED=false`。该闸门在
工作流创建、批量启动、旧消息确认、批次重试、Agent 受控动作和 Workflow Worker
执行入口统一生效；读取已有任务状态仍允许。只有取得真实 FQDN、出站策略、合成回归和
管理员批准后，才可以在受控环境中显式改为 `true`。

## 已验证与未执行项

- Pi Runtime、模型网关、工作流阶段动作、上下文权限和灰度选择均有合成测试。
- OpenAPI 契约检查、前端类型检查、生产构建、Agent Runtime 构建和 Compose 配置检查已通过。
- 本次没有启动 `ar-hexiao-daily`，没有访问智云，也没有执行真实取数、写表或 Worker 回归。
- Docker Desktop Linux Engine 已恢复，`api`、`next` 镜像已重建，生产 Compose 已启动；API 健康检查和前端入口已验证。
- 生产环境默认使用 Pi；`AGENT_RUNTIME_FALLBACK=legacy` 只处理 Pi 在尚未产生文本或业务工具事件时的初始化故障，已调用工具的会话不会重放。
- 模型网关只接受标准采样字段，拒绝客户端控制的上游缓存、持久化和供应商路由字段；SSE 响应已纳入根 OpenAPI 契约。
- 新任务不创建也不强制管理员审批记录；历史审批记录和兼容接口仍保留为只读/兼容用途。任务失败时，
  工作流进度卡片展示员工、Skill、失败步骤和脱敏后的失败原因。
- 文件中心按 Skill 分组展示文件；每次运行产生的交付文件使用独立文件记录并保留历史版本，不覆盖既有记录。
