# GitHub 同类开源项目调研与平台改造建议

日期：2026-08-15

## 1. 调研目的

本次调研不是为平台寻找一个可直接替换的成品，而是寻找适合当前财务 Skill 平台的架构、页面布局、AI 交互和工作流编排做法。

当前平台已经具备需要保留的基础能力：Next.js 前端、FastAPI 服务、PostgreSQL、独立 Worker 池、Skill Manifest、用户与部门隔离、写入审批、审计事件、任务草稿、发布审核和受控文件下载。后续改造应继续保证：AI 负责理解需求、推荐 Skill、整理参数和解释结果；确定性脚本、RPA 或内部 API 执行业务；模型不能直接绕过权限、审批和文件校验。

## 2. 结论

不建议废弃当前平台，也不建议整体移植 Dify、n8n 或 Windmill。当前平台的财务安全边界比多数通用 AI 工作流产品更贴合实际业务，主要欠缺的是产品结构、统一任务体验、可视化运行过程和 AI 可观测性。

推荐采用组合参考方案：

1. 参考 Dify 的产品信息架构、模型管理、任务调试和工作流画布。
2. 参考 Activepieces 的连接器定义、版本化流程、重试和人工审批节点。
3. 参考 Kestra 的声明式工作流、运行拓扑、事件日志和失败重跑。
4. 参考 Temporal 的状态持久化、事件历史、确定性流程和幂等 Activity 原则。
5. 后期接入 Langfuse 或兼容 OpenTelemetry 的链路数据，记录模型调用、延迟、用量、结果质量和脱敏后的错误。

近期最值得做的是重组页面与任务路径，并补齐步骤级运行模型。暂时不要先做可任意拖拽、可执行任意代码的通用画布。

## 3. 候选项目比较

| 项目 | 主要价值 | 适合借鉴 | 不建议直接采用的原因 | 适配度 |
| --- | --- | --- | --- | --- |
| [Dify](https://github.com/langgenius/dify) | AI 应用、工作流、RAG、Agent、模型和 LLMOps 集成在同一工作区 | 产品分区、模型供应商抽象、工作流调试、节点运行详情、知识与工具分离 | Dify 以通用 LLM 应用为中心，不能替代财务审批和确定性执行；许可证限制多租户使用、前端品牌修改，且交互设计声明受外观专利保护，不应复制代码或像素级界面 | 高，限产品与交互参考 |
| [Activepieces](https://github.com/activepieces/activepieces) | 类型化连接器、流程版本、重试、人工审批、表单和聊天入口 | 将智云、易快报、文件、模型等统一为受控连接器；连接器输入输出 Schema；审批节点和版本记录 | 社区版为 MIT，但部分企业功能使用商业许可证；通用连接器需要再套一层平台权限和凭据隔离 | 很高 |
| [Kestra](https://github.com/kestra-io/kestra) | 事件驱动和定时编排、声明式 YAML、插件、运行拓扑与日志 | 步骤图、计划任务、失败步骤重跑、运行变量、事件时间线、工作流版本 | Java/Vue 技术栈和完整调度平台偏重，现阶段整体接入会增加运维复杂度 | 高，先借鉴模型和页面 |
| [Temporal](https://github.com/temporalio/temporal) | 持久化执行、事件历史、自动恢复、任务队列、Workflow/Activity 分离 | 长任务恢复、幂等写入、可重放状态、Worker 路由、超时和重试策略 | 它是执行基础设施，不提供完整业务后台；引入后需要改造现有 Worker 和状态模型 | 中高，任务量上升后评估 |
| [Windmill](https://github.com/windmill-labs/windmill) | 脚本、Flow、后台任务、Worker 和内部应用一体化 | 脚本与流程分层、Worker 标签、运行队列、自动表单、资源和凭据抽象 | 前后端主要为 AGPLv3，预构建社区版还包含额外限制和专有功能；不适合直接复制或包装进现有产品 | 高，限架构和界面参考 |
| [Langfuse](https://github.com/langfuse/langfuse) | LLM 链路、评测、指标、提示词和数据集管理 | 模型 Trace、会话、工具调用、延迟、Token、失败原因和人工评分 | OSS 主体为 MIT，但 `ee` 目录和部分企业能力不是 MIT；财务原文、账号、文件名和模型输入必须在发送前脱敏 | 很高，适合作为可选观测组件 |
| [Flowise](https://github.com/FlowiseAI/Flowise) / [Langflow](https://github.com/langflow-ai/langflow) | 可视化 AI 节点、Agent/RAG 原型和组件库 | 节点选择器、端口类型、参数侧栏、测试运行、输入输出预览 | 运行模型偏 LLM/Agent，允许的组件范围过宽；不适合承载财务写入授权和生产执行 | 中，限画布设计参考 |
| [n8n](https://github.com/n8n-io/n8n) | 成熟的自动化画布、连接器、执行历史和人工确认 | 连接器目录、节点配置、错误分支、执行数据查看 | 官方明确采用 Sustainable Use License 和企业许可证，不属于 OSI 开源；嵌入、改名或对外提供能力需要单独评估 | 中，限概念参考 |
| [Open WebUI](https://github.com/open-webui/open-webui) | 对话、文件上下文、工具结果和模型切换体验 | 对话历史、附件提示、来源卡片、工具调用过程展示 | 新版本有品牌保留条件；工具创建近似服务器代码执行权限，不符合普通财务用户的最小权限要求 | 低，限 AI 对话细节参考 |

## 4. 当前平台的主要差距

### 4.1 信息架构

当前侧栏把员工业务、管理员功能和模板演示页面放在同一组。`产品管理`、`任务看板`、`在线沟通`、`账单管理`、`表单`、`图标/组件演示` 等页面与财务 Skill 主流程关系较弱，会让用户难以判断从哪里开始。

建议调整为：

| 分组 | 页面 | 说明 |
| --- | --- | --- |
| 我的工作 | 工作台、Skill 中心、我的任务、文件中心、AI 助手 | 普通员工的完整使用路径 |
| 待办 | 待我确认、待我审批 | 将任务确认和写入审批聚合成待办入口 |
| 管理 | Skill 治理、组织与成员、权限、审计记录 | 仅管理员可见 |
| 系统 | 模型与连接器、运行资源、系统设置 | 仅平台管理员可见 |

模板演示页先从生产导航隐藏，确认没有真实业务依赖后再删除代码。Skill 发布、审核、历史记录应归入 `Skill 治理`，不再散落在 Skill 详情页和独立的同级菜单中。

### 4.2 统一任务路径

AI 助手、Skill 目录和任务中心当前是三个入口，但用户执行任务时缺少统一过程。建议无论入口来自哪里，都进入同一个任务向导：

`选择或识别 Skill → 绑定文件和参数 → 自动预检 → 用户确认 → 执行 → 必要时审批 → 写入与复核 → 下载结果`

任务详情页建议使用三栏或主区加抽屉：

- 顶部显示状态、当前步骤、发起人、Skill 版本、耗时和风险等级。
- 主区显示步骤时间线，明确哪些步骤由 AI、脚本、人工或外部系统完成。
- 右侧显示当前步骤的输入、输出、文件哈希、审批状态和可执行操作。
- 日志默认显示业务事件，技术日志放到次级页签，避免普通用户看到大量内部堆栈。

### 4.3 工作流模型

现有 `RunRecord`、`RunEvent`、`WorkflowSession` 和多个 Worker 已经能够支撑第一版，不必立刻引入新的编排引擎。建议先增加平台自己的步骤级模型：

- `WorkflowDefinition`：工作流定义和版本。
- `StepDefinition`：步骤类型、输入输出 Schema、重试、超时、风险等级和 Worker 路由。
- `StepRun`：每次执行的状态、开始结束时间、输入输出摘要、错误和重试次数。
- `ArtifactBinding`：步骤与输入/输出文件、哈希和用途的关系。
- `ApprovalBinding`：审批与具体步骤、文件快照、Skill 版本和有效期的关系。

第一批允许的步骤类型固定为：参数校验、文件校验、内部 API 只读、Python 脚本、RPA、结果预览、人工确认、管理员审批、受控写入、写后复核、产物归档。管理员可以编排这些受控步骤，但不能在网页中创建任意 shell 或任意 Python 节点。

每个写入步骤必须满足：输入快照不变、审批仍有效、幂等键存在、写前备份成功、写后读回通过。失败重试只重试当前可安全重试的步骤，不能默认从头执行整个财务任务。

### 4.4 AI 设计

建议把 AI 从独立聊天页逐步改造成任务过程中的助手，同时保留单独入口供需求探索：

1. AI 先输出严格 Schema 的 `TaskDraft`，包含推荐 Skill、候选 Skill、置信度、参数、缺失文件和说明。
2. 置信度不足或候选冲突时只提澄清问题，不创建可执行任务。
3. AI 可以解释 Skill 说明和任务结果，但不能产生审批结论、修改结果文件或调用写入步骤。
4. AI 工具只暴露平台定义的只读能力和草稿能力；真正执行仍经过后端权限、Manifest、文件哈希和审批校验。
5. 每次模型调用记录模型、提示词版本、工具、延迟、Token、脱敏后的错误和用户反馈。原始财务文件内容默认不发送到外部观测服务。
6. Skill 数量增加后，可用 pgvector 对 Skill 说明、输入条件和示例做语义召回；召回只用于候选选择，最终仍按权限和结构化规则过滤。

### 4.5 页面视觉

平台适合采用数据密集但层级明确的后台布局：状态色固定、筛选始终可见、表格支持保存视图、风险操作与普通操作分离。继续使用当前 shadcn 组件和语义色，不复制其他项目的品牌主题。

建议统一以下页面模式：

- 工作台：我的待办、最近任务、常用 Skill、失败任务和审批提醒。
- 列表页：顶部统计、固定筛选栏、表格、批量操作和右侧详情抽屉。
- Skill 详情：用途、所需资料、流程、权限、版本、最近运行和审核记录分标签展示。
- 工作流编辑：左侧受控节点库、中间画布、右侧参数配置、底部测试与校验结果。
- AI 助手：会话区旁固定显示任务草稿卡，用户可直接检查 Skill、文件和参数，确认后进入任务详情。

## 5. 推荐目标架构

保持 Next.js、FastAPI、PostgreSQL、Caddy 和现有 Worker 池。新增能力按以下边界组织：

```text
Next.js 工作台
  ├─ Skill 中心 / AI 助手 / 任务向导
  ├─ 任务详情 / 步骤时间线 / 结果
  └─ Skill 治理 / 审批 / 审计 / 系统设置
              │
FastAPI 控制层
  ├─ 身份、RBAC、资源隔离
  ├─ Skill Registry 与发布审核
  ├─ TaskDraft 与模型供应商
  ├─ Workflow Definition / StepRun 状态机
  ├─ 审批、幂等、文件哈希和审计
  └─ Connector / Credential 抽象
              │
Worker 执行层
  ├─ HTTP 只读与内部 API
  ├─ Python 确定性任务
  ├─ RPA 浏览器任务
  └─ Workflow 协调任务
              │
PostgreSQL / 受控文件存储 / 可选 Redis / 可选 Langfuse
```

Redis 在需要跨进程队列、分布式锁或更高并发时加入。Temporal 或 Kestra 只在长任务恢复、定时流程和跨系统编排明显超过当前状态机能力时再进行验证性接入。

## 6. 实施顺序

### P3-01 页面与导航整理

- 重组侧栏为我的工作、待办、管理、系统。
- 隐藏模板演示模块。
- 合并 Skill 发布、审核和记录为 Skill 治理。
- 统一空状态、状态徽标、筛选和详情抽屉。

验收：员工角色只能看到工作相关页面；管理员菜单不会干扰员工主路径；任何任务从工作台、Skill 或 AI 入口进入同一任务详情。

### P3-02 任务详情与步骤时间线

- 增加 WorkflowDefinition、StepDefinition、StepRun 和 ArtifactBinding。
- 将现有 RunEvent 映射为用户可读事件和技术事件。
- 增加步骤输入输出快照、重试策略和失败原因展示。

验收：能够清楚回答任务执行到哪一步、使用了什么输入、为什么失败、能否重试、生成了哪些文件。

### P3-03 受控工作流编排

- 建立固定节点类型和 Schema。
- 为管理员提供只读工作流画布与校验器，稳定后再允许编辑。
- 将审批和写后复核作为平台节点，不允许 Skill 自行绕过。

验收：非法连接、缺失输入、未审批写入和非幂等重试均在执行前被拒绝。

### P3-04 AI 助手融合

- 将 TaskDraft 卡片嵌入统一任务向导。
- 增加候选原因、置信度、缺失条件和模型调用状态。
- 建立提示词版本和离线评测集。

验收：模型不可用时用户仍可手工运行 Skill；模型输出不能直接改变执行状态；低置信度不会自动发起任务。

### P3-05 观测与运营

- 先在本地数据库记录模型 Trace 摘要和步骤指标。
- 确认脱敏方案后再选择性接入 Langfuse/OpenTelemetry。
- 增加失败率、平均耗时、排队时间、重试次数、人工介入率和模型费用看板。

验收：不泄露财务原文和凭据；能按用户、Skill、版本、模型和时间查询问题。

## 7. 不建议做的事项

- 不整体换成 Dify、n8n、Windmill 或 Open WebUI。
- 不复制受许可证、品牌条款或外观权利限制的前端代码和视觉稿。
- 不让大模型直接访问数据库、文件系统、浏览器凭据或写入 API。
- 不先建设任意代码节点和面向普通员工的自由画布。
- 不把审批只做成界面按钮；审批必须绑定输入、文件哈希、Skill 版本和有效期，并由后端强制执行。
- 不把技术日志直接当作业务进度；两类信息需要分层展示。

## 8. 采用建议

当前阶段可直接采用的是设计方法和数据模型，不引入新的大型运行时。先完成 P3-01、P3-02 和 P3-04，平台的完整度会有明显改善；P3-03 在两个以上多步骤 Skill 稳定运行后实施；Langfuse、Temporal 或 Kestra 作为后续独立技术验证，不进入当前主链路。

## 9. 主要来源

- [Dify GitHub 与许可证](https://github.com/langgenius/dify)
- [Activepieces GitHub](https://github.com/activepieces/activepieces)
- [Kestra GitHub](https://github.com/kestra-io/kestra)
- [Temporal GitHub 与架构说明](https://github.com/temporalio/temporal/tree/main/docs/architecture)
- [Windmill GitHub 与许可证](https://github.com/windmill-labs/windmill/blob/main/LICENSE)
- [Langfuse GitHub 与许可证](https://github.com/langfuse/langfuse/blob/main/LICENSE)
- [Flowise GitHub](https://github.com/FlowiseAI/Flowise)
- [Langflow GitHub](https://github.com/langflow-ai/langflow)
- [n8n GitHub](https://github.com/n8n-io/n8n)
- [n8n Sustainable Use License](https://github.com/n8n-io/n8n-docs/blob/main/docs/privacy-and-security/sustainable-use-license.md)
- [Open WebUI GitHub](https://github.com/open-webui/open-webui)

