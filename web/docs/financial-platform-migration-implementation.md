# 财务 Skill 平台迁移实施方案

## 1. 目标与边界

本目录是统一仓库中的唯一用户界面，继续使用 Next.js、shadcn/ui、现有主题系统和 Clerk。同一仓库根目录下的 `backend/`、`skills/`、`deploy/` 和 `scripts/` 提供 FastAPI、Skill Registry、任务与工作流、文件、审计、Worker 和 Scheduler。

```text
用户
  -> 当前 Next.js 项目（页面、Clerk、主题、交互）
  -> 受控平台 API 适配层
  -> financial_pj FastAPI（业务权限、数据和执行）
  -> Worker / Skill / 文件存储
```

迁移期间遵守以下边界：

- 不重新初始化或替换当前前端框架。
- 不复制旧 Vite 前端的组件和样式，只迁移业务能力与接口契约。
- Clerk 负责身份认证；平台后端负责部门、角色、Skill 权限、数据范围、审批和发布权限。
- 前端菜单隐藏不构成安全控制，所有资源访问均由 FastAPI 复核。
- 未完成审批硬闸和网络隔离前，写入外部系统或修改原始数据的 Skill 保持禁用。
- 测试只使用合成或脱敏数据，不把 Token、Cookie、密码、API Key 和业务凭据写入日志。

## 2. 目标目录

当前项目按 feature-based 结构增加：

```text
src/
  app/api/platform/          # 明确列出的服务端 BFF 路由，不提供任意路径代理
  features/platform-api/     # 类型、错误、服务端客户端和查询键
  features/skills/
  features/runs/
  features/files/
  features/assistant/
  features/audit/
  features/access-control/
```

目录合并已经完成：Next.js 位于 `web/`，FastAPI 和 Alembic 位于 `backend/`，运行 Skill 位于 `skills/`，Skill 原始源码位于 `sources/finance-skills/`。

## 3. 分阶段实施

### 阶段一：基线、备份和回滚点

1. 分别保存当前项目中文化与 Clerk 状态，以及 `financial_pj` 的认证、安全迁移和 Skill 状态。
2. 备份数据库、上传文件、运行结果、工作流文件和 Manifest，并验证恢复路径。
3. 保存 FastAPI OpenAPI、数据库迁移 head、测试结果和当前运行配置。
4. 为迁移建立独立分支，禁止批量清理两个现有脏工作树。

验收：两个项目均可从保存点恢复，构建和测试可复现，备份不包含未受控密钥副本。

### 阶段二：Clerk 身份桥接与 API 边界

1. Next.js 服务端通过 Clerk `auth()` 获取 Session Token。
2. Next.js 只通过明确列出的 BFF 路由访问 FastAPI，不建立可转发任意 URL 的开放代理。
3. FastAPI 验证 Bearer Token 的签名、有效期、issuer、audience 和 authorized party。
4. 使用 Clerk `sub` 映射平台本地用户；平台角色和权限仍从平台数据库读取。
5. 新 Clerk 身份不得自动成为管理员；未映射或禁用身份默认拒绝。
6. 迁移期允许显式配置 `session`、`hybrid`、`clerk` 三种认证模式。请求携带 Bearer Token 时验证失败必须直接拒绝，不能退回 Cookie。
7. 旧 Cookie 登录只作为迁移回退能力；新 Next.js 前端不使用平台密码登录。
8. 文件下载、上传、SSE 和普通 JSON 请求使用同一身份边界。

验收：匿名 401、无效 Token 401、未映射身份 403、禁用用户 401/403、员工访问管理接口 403、伪造 `X-User-*` 无效；旧 Cookie 回退仅在配置允许时生效。

### 阶段三：领域模型和 API 契约

冻结 `PlatformUser`、`SkillSummary`、`SkillDetail`、`RunSummary`、`RunDetail`、`RunEvent`、`PlatformFile`、`AuditEvent`、`TaskDraft` 和 `ApprovalRecord`。员工 DTO 与管理员 DTO 分离，前端类型由 OpenAPI 或单一契约生成。暂缺接口只能通过统一 Mock Adapter 提供，并明确标注 Mock；权限和任务执行不得 Mock。

### 阶段四：第一条端到端链路

使用一个只读或仅生成副本的 Skill，贯通 Clerk 登录、Skill 列表、Skill 详情、文件上传、参数确认、创建任务、SSE 进度、结果展示、文件下载和审计。首批只开放 3 至 5 个安全 Skill。

### 阶段五：工作台、任务中心和文件中心

新增 `/api/workbench` 聚合接口，避免浏览器拉取全量数据后统计。补齐运行分页、失败定位、重试约束、文件列表、文件详情、保留期限、下载审计和引用删除规则。

### 阶段六：AI 助手与 TaskDraft

AI 只生成不可执行草稿。后端在授权 Skill 集合中推荐并校验参数；用户确认时重新验证权限、Skill 版本、文件 ID 和 SHA-256，随后才创建 Run。模型输出不得直接进入 Worker。

### 阶段七：用户、角色、权限与审计

先使用固定平台角色和明确能力，不在第一版引入通用策略语言。Clerk 用户信息只读，平台数据库保存部门、业务角色、Skill 权限和数据范围。权限变更、下载、运行、审批和管理员读取均写入脱敏审计。

### 阶段八：Skill 创建、编辑和版本发布

第一版支持元数据草稿、受控包导入、结构校验、测试、审核、发布和回退，不提供任意在线代码执行器。可执行代码仍需经过 Git、测试和受控同步。

### 阶段九：审批与写入型任务

实现双人审批、变更预览、不可变执行快照、审批过期、Worker 领取硬闸、网络出站限制、写后回读、幂等复核和原文件哈希保护。全部验收前不得恢复写入型 Skill。

### 阶段十：部署、数据库迁移与旧前端下线

部门正式试用前完成 PostgreSQL 迁移和并发验证。通过同一 HTTPS 入口提供 Next.js 和 FastAPI；Worker 不暴露给用户网络。新旧结果对比、回滚演练和小范围试用通过后再停止旧 Vite 前端。

## 4. 第一批交付范围

第一批实现：

```text
/dashboard/overview
/dashboard/skills
/dashboard/skills/[skillId]
/dashboard/runs
/dashboard/runs/[runId]
/dashboard/files
/dashboard/users
```

第一批暂缓：Skill 在线代码编辑、动态策略语言、AI 自动执行、写入型 Skill、双人审批、公网开放、Redis、MinIO 和 pgvector。

## 5. 阶段二技术决策

### 5.1 Token 流程

```text
Clerk 登录
  -> Next.js Server Component / Route Handler 调用 auth().getToken()
  -> Authorization: Bearer <session-token>
  -> FastAPI 校验 Clerk JWT
  -> claims.sub 查找 users.clerk_user_id
  -> 读取平台 role / department_id / status
  -> 执行业务权限检查
```

### 5.2 用户映射

- `users.clerk_user_id`：可空、唯一；由管理员明确绑定。
- `users.clerk_organization_id`：可空，用于限制 Clerk 组织边界。
- 未映射 Clerk 身份返回 403，不自动创建可用账号。
- 管理员绑定和解绑 Clerk 身份必须写审计。
- 不从邮箱、前端参数或 Clerk 显示角色自动推导平台管理员。

### 5.3 认证模式

- `session`：仅旧平台 Cookie，用于回滚。
- `hybrid`：无 Bearer 时可使用旧 Cookie；Bearer 存在时必须验证成功。
- `clerk`：仅接受 Clerk Bearer Token，用于切换完成后的正式入口。

现有运行环境默认保持 `session`。完成 Clerk issuer、authorized party 和管理员 Clerk ID 配置后切换为 `hybrid`，新前端验收完成后正式环境再切换 `clerk`。

### 5.4 BFF 边界

Next.js 只增加显式平台路由，例如 `/api/platform/session`。后续上传、下载和 SSE 分别实现，不通过一个任意 catch-all 代理暴露 FastAPI 管理端点。

## 6. 验证矩阵

| 场景 | 预期 |
| --- | --- |
| 无 Cookie、无 Bearer | 401 |
| 无效 Bearer，同时存在有效旧 Cookie | 401，不回退 |
| 有效 Bearer、未绑定平台用户 | 403 |
| 有效 Bearer、平台用户被禁用 | 401/403 |
| 有效 Bearer、普通员工访问管理接口 | 403 |
| 有效 Bearer、管理员访问管理接口 | 200 |
| 伪造 `X-User-Role` | 身份和权限不变 |
| `session` 模式使用旧 Cookie | 保持兼容 |
| `clerk` 模式仅有旧 Cookie | 401 |
| 文件、SSE 和 JSON 接口 | 使用相同用户映射和资源隔离 |

## 7. 实施进度

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| 阶段一 | 已完成 | 数据、OpenAPI、测试基线均已保存；两个脏工作树已建立 Git 基线 bundle、tracked patch、untracked ZIP 和 SHA-256 清单，不包含 Git 忽略文件或生产密钥 |
| 阶段二 | 已完成并部署 | Clerk issuer、authorized party、管理员映射和 `hybrid` 模式已接入真实数据库；8001 实例健康，匿名与无效 Bearer 边界已验证 |
| 阶段三 | 已完成 | 核心领域 DTO、员工/管理员 Skill DTO、OpenAPI 0.2.0 快照、生成型 TypeScript 与契约漂移检查均已实现 |
| 阶段四 | 已完成 | Clerk 登录态下已使用合成数据完成 `reconcile-bank` 端到端试运行，目录、详情、上传、参数确认、任务创建/确认、SSE 进度、结果展示、受控下载和下载审计均已验收 |
| 阶段五 | 已完成 | 工作台聚合、任务分页与受控重试、文件列表与详情、保留日期、下载审计和引用删除规则均已实现并完成运行态验收 |
| 阶段六 | 已完成并部署 | 已实现部门默认模型档案、AI 推荐、不可执行 TaskDraft、用户确认硬闸、显式 BFF 和中文助手页面；真实库已升级到 `d7e5a3f91c42` |
| 阶段七 | 已完成并部署 | 已实现本部门平台用户、固定角色、Clerk 映射、Skill 权限矩阵和脱敏审计查询；部门隔离、默认拒绝与敏感读取审计已完成回归和运行态验收 |
| 阶段八 | 已完成并部署 | 已实现受控包导入、结构与完整性校验、业务元数据编辑、审核、发布、回退、跨进程互斥和脱敏审计；真实库已升级到 `f4a9c2e71b30` |
| 阶段九 | 已完成并部署 | 双人审批、变更预览、不可变快照、审批过期、Worker 双重硬闸、原文件哈希和应用级精确域名策略均已部署 |
| 阶段十 | 平台部署与出站隔离已完成，写入发布受外部条件限制 | PostgreSQL、统一 HTTPS、Worker 进程外隔离、CONNECT 精确域名代理、并发、备份恢复、回滚和合成只读试运行均通过；真实智云 HTTPS FQDN、现场证书/路由验收及管理员恢复发布批准未提供，写入型 Skill 继续 disabled |

### 2026-08-14 阶段二执行记录

- FastAPI 新增 Clerk JWT 验证模块，校验 RS256、issuer、时间声明、可选 audience 与 authorized party。
- `users` 新增唯一 `clerk_user_id` 和可选 `clerk_organization_id`；Alembic head 为 `b1a76f93c2de`。
- 管理员接口支持显式绑定或解除 Clerk 身份，绑定变更进入脱敏审计。
- 新增 `session`、`hybrid`、`clerk` 三种认证模式；Bearer 验证失败不得退回 Cookie。
- Next.js 新增服务端平台客户端和显式 `/api/platform/session`，平台地址不暴露到浏览器。
- FastAPI 完整测试 120 项通过；新增 8 项 Clerk 认证测试覆盖真实 RSA 签名、用户映射、组织限制、禁用用户和降级防护。
- Next.js 类型检查、lint 和生产构建通过；构建产物包含 `/api/platform/session`。
- 真实 SQLite 数据库已备份并升级到 `b1a76f93c2de`，目标 Clerk 应用用户已显式绑定平台唯一管理员；运行模式已切换为 `hybrid`，旧 Session 登录仍作为迁移回退。
- 平台已在 `127.0.0.1:8001` 运行，19 个 Skill、0 个 Registry 错误、6 个 Worker；无 Bearer 请求仍按 Session 处理，无效 Bearer 直接按 Clerk 拒绝。

### 2026-08-14 阶段三执行记录

- 新增平台领域词汇表，固定 Platform User、Skill、Run、Run Event、Platform File、Task Draft、Approval Record 和 Audit Event 的含义，明确 Clerk 用户不等于平台用户、任务草稿不能直接执行。
- FastAPI 新增 `PlatformUser`、`SkillSummary`、`SkillDetail`、`AdminSkillDetail`、`RunSummary`、`RunDetail`、`RunEventRead`、`PlatformFile`、`AuditEventRead`、`TaskDraft` 和 `ApprovalRecord` 契约。
- `/api/session`、健康检查、Skill、上传、任务摘要/详情和 Registry 重载补齐显式响应模型；管理员与员工 Skill DTO 分离，员工 DTO 不含 handler、runtime、permissions、source、skill_hash 和输出实现结构。
- 新增确定性 OpenAPI 导出与 `--check`；仓库根目录统一保存 `contracts/financial-platform.openapi.json`，Next.js 使用 `openapi-typescript` 生成 `src/features/platform-api/generated.ts`，业务代码只引用稳定别名。

### 2026-08-14 阶段四第一段执行记录

- FastAPI 新增 `/api/catalog/skills` 和 `/api/catalog/skills/{skill_id}`，始终返回员工安全视图；管理员访问时也不暴露执行入口、脚本路径、运行配置和来源字段。未授权员工仍返回空目录或 404。
- Next.js 新增 `/api/platform/skills`、`/api/platform/skills/[skillId]` 两条显式 BFF，以及 `/dashboard/skills`、`/dashboard/skills/[skillId]` 页面和侧边栏入口。
- 详情页展示所需文件、参数、风险、预计耗时、预期结果和处理阶段；页面明确不直接启动 Worker，文件上传和任务创建继续按后续步骤接入。
- 后端完整测试 124 项通过；Next.js 契约检查、类型检查、lint 和生产构建通过。lint 保留 5 条既有嵌套组件警告；构建保留 Google Sans Flex fallback 与 `metadataBase` 两类既有警告。

### 2026-08-14 阶段四第二段执行记录

- Next.js 新增文件上传、临时文件删除、任务创建和任务确认四类显式 BFF；平台 API 地址与 Clerk Bearer 仍只存在于服务端。
- BFF 在上传和创建任务前重新读取员工 Skill 详情，只允许首批试运行清单中的已发布、标准、只读且不修改原上传文件的 Skill；浏览器不能提交模型连接或其他额外运行字段。
- 首批开放 `reconcile-bank`、`split-by-sales`、`receivables-merge`、`dreame-ar-progress-diff` 和 `order-daily-summary`，覆盖单文件、可选文件、多文件、数值、字符串和布尔参数。其他 Skill 只展示说明，暂不允许创建任务。
- Skill 详情页支持按角色和清单约束上传文件、删除临时文件、填写并校验参数、查看最终确认清单；确认后依次创建任务并调用平台确认接口。若确认失败，保留任务编号并允许重试，不重复创建任务。
- 未使用真实财务文件或创建真实任务。Next.js 契约检查、类型检查、针对新增文件的 lint、格式检查和生产构建通过；构建仍保留 Google Sans Flex fallback 与 `metadataBase` 两类既有警告。

### 2026-08-14 阶段四第三段执行记录

- Next.js 新增任务列表、任务详情、SSE 事件流和结果文件下载四类显式 BFF；SSE 代理在服务端附加 Clerk Bearer，并把浏览器 `Last-Event-ID` 转换为后端 `after` 游标，避免重连后丢失进度。
- 新增 `/dashboard/runs` 和 `/dashboard/runs/[runId]`，支持任务状态、进度、输入摘要、最近 100 条事件、结果指标和输出文件展示；创建任务成功后可以直接进入实时详情页。
- 下载路由先读取当前任务并核对文件 ID 属于 `result.output_files`，再流式转发文件；不接受任意平台文件路径，也不把 FastAPI 地址或 Clerk Token 暴露给浏览器。
- FastAPI 文件下载接口新增 `file.download` 脱敏审计，记录文件 ID、类型、大小、SHA-256 和任务 ID，不记录文件名或文件内容；下载仍执行用户/部门所有权和存储根目录检查。
- 后端全量 124 项测试通过，新增下载审计断言；退出时保留一条 Windows pytest 临时目录清理权限警告，退出码为 0。Next.js 类型、契约、针对新增文件的 lint 和格式检查通过。
- 8001 服务在确认无活动 Run 和 Workflow Action 后重启，API 与 6 个 Worker 均恢复。截至该段完成时没有上传真实财务文件或创建真实任务，端到端验收尚待 Clerk 登录问题处理后进行。

### 2026-08-14 阶段四端到端验收记录

- 使用 Clerk 已绑定的平台管理员登录，通过 Next.js 页面选择 `reconcile-bank`；上传两份仅含 3 行合成记录的 Excel，没有使用真实财务文件。
- 页面按金额容差 1 元、日期容差 2 天完成输入确认，任务 `1d010e6b-1b8a-412a-aae6-ec6b32257422` 经创建、确认、排队、Worker 领取和执行后成功结束，进度为 100%。
- 页面结果为银行流水 3 条、总账 3 条、成功匹配 2 条、银行未匹配 1 条、总账未匹配 1 条；结果工作簿的三个工作表和明细行数经独立回读与渲染检查一致，未发现公式错误。
- 首次验收发现终态任务页面不会订阅历史 SSE，导致处理记录一直显示“正在读取任务事件”；已修复终态提前返回逻辑，刷新后完整显示 10 条事件，浏览器回归信号由 RED 变为 GREEN。
- 结果下载通过 Next.js 受控路由完成，后端生成 `file.download` 成功审计，仅记录文件 ID、类型、大小、SHA-256 和任务 ID，不记录文件名或内容。
- Next.js 定向 lint、类型检查和生产构建通过；后端 `test_platform_e2e.py` 4 项通过。构建仍保留 Google Sans Flex fallback 与 `metadataBase` 两类既有警告。
- 阶段四验收完成，下一实施阶段为阶段五“工作台、任务中心和文件中心”。

### 2026-08-14 阶段五执行记录

- FastAPI 新增 `/api/workbench` 聚合接口，一次返回当前用户可见的任务统计、常用 Skill、待处理任务、最近结果和最近文件；前端不再下载全量任务和文件后自行统计。
- `/api/runs` 改为服务端分页，任务摘要和详情补充失败原因、是否允许重试及阻断原因；`POST /api/runs/{run_id}/retry` 只允许失败或超时的只读任务，并重新校验当前权限、Skill 版本、输入文件存在性和 SHA-256。重试创建新任务，同一来源任务重复请求保持幂等。
- 新增文件分页、文件详情和通用受控下载 BFF。文件响应按 `FINANCIAL_FILE_RETENTION_DAYS` 返回保留日期，默认 90 天；本阶段不自动清理文件。结果文件不能单独删除，已经被任何任务或工作流引用的上传文件也不能删除，以保留审计和重试证据。
- Next.js 数据概览已替换原模板模拟收入、客户和图表，改为真实员工工作台；任务中心增加状态筛选、分页和失败定位；新增文件中心、文件名查询、类型筛选、分页、下载和受控删除入口。
- 后端全量测试 127 项通过，新增第五阶段测试覆盖工作台隔离、任务分页、文件保留日期、引用删除规则、只读任务重试、重试幂等和审计；仅保留既有 Starlette/httpx 弃用警告及 pytest 临时目录权限提示。
- Next.js 契约漂移检查、类型检查、定向 lint 和生产构建通过；构建仍保留 Google Sans Flex fallback 与 `metadataBase` 两类既有警告。
- 确认无活动 Run、Workflow Action 和执行中 Workflow 后，8001 实例已安全重启，健康检查为 `ok`、19 个 Skill、0 个 Registry 错误、6 个 Worker。使用现有 Clerk 管理员登录态完成工作台、任务中心和文件中心页面验收；未创建新任务，未删除或下载真实文件。

### 2026-08-14 阶段六执行记录

- FastAPI 新增部门级默认助手模型档案和持久化 TaskDraft。管理员从部门已有模型连接中选择默认模型；员工接口只返回是否已配置，不返回厂商、模型或密钥提示。
- `POST /api/assistant/prepare` 只向模型提供当前用户获准创建草稿、已发布、标准、只读且不修改上传文件的 Skill 安全目录；上传文件使用 `F1`、`F2` 等临时别名，模型不能看到存储路径或生成任意文件 ID。
- 模型必须返回受约束的结构化工具调用。后端重新校验候选 Skill、参数 JSON Schema、安全范围、文件角色、格式、大小、所有权和 SHA-256；置信度不低于 0.85 时只展示一个推荐，0.60 到 0.85 最多展示三个候选，低于 0.60 必须提出澄清问题。
- 新增草稿读取、修改、删除和确认接口。草稿确认时重新检查用户权限、Skill 版本与哈希、文件记录和磁盘 SHA-256，随后才创建 Run；写入型、外部动作型和需要审批的 Skill 当前不能从助手直接执行。重复确认使用草稿幂等键返回同一 Run。
- Next.js 新增助手状态、草稿、确认、管理员模型档案和模型连接的显式 BFF；`/dashboard/ai-chat` 已替换模板演示，提供中文任务描述、文件选择、推荐置信度、参数和文件分配预览、缺失材料提示及明确确认按钮。
- 后端完整测试 131 项通过；新增测试覆盖生成草稿不创建 Run、确认后创建、重复确认幂等、文件变化阻断、跨用户隔离、管理员配置隔离、未配置提示和未授权推荐拒绝。Next.js 契约检查、类型检查、本阶段 lint 和生产构建通过。
- 部署前确认没有活动任务。备份工具补充 Windows 长路径复制与回读支持，真实数据目录的数据库和 142 个业务文件已通过集合及 SHA-256 校验，备份为 `data/backups/20260814_140409_pre-stage6-assistant-verified`。真实数据库升级到 `d7e5a3f91c42`，8001 API 与 6 个 Worker 已恢复健康。
- 运行态使用现有 Clerk 管理员登录验证页面成功，两个模型连接和各自模型列表正常显示，浏览器控制台没有错误。当前有两个可用连接，未代管理员选择默认模型，因此助手输入保持禁用，需由管理员在页面保存选择后使用；本次未调用真实模型、未创建任务、未读取真实财务文件内容。

### 2026-08-14 阶段七执行记录

- FastAPI 把管理员用户操作集中到单一服务模块。用户列表、创建、更新和 Skill 授权只能作用于当前管理员所属部门；跨部门目标统一按不存在处理，不能创建其他部门账号，也不能禁用或移除当前登录管理员的管理员角色。
- 固定角色继续使用 `finance_user` 和 `skill_admin`。管理员默认拥有当前部门全部 Skill 管理权限且不保存逐项授权；员工默认无权限，只能获授已发布 Skill 的运行、上传、创建草稿和需审批能力。Clerk 仅提供外部身份，平台数据库仍负责角色、部门和 Skill 权限。
- 用户列表读取和审计列表读取新增脱敏审计；权限替换、用户创建、账号状态、角色和 Clerk 映射更新继续写审计。审计筛选限制字段长度和返回数量，前端只展示平台返回的脱敏详情。
- Next.js 新增用户、单用户更新、权限替换和审计查询四类显式 BFF；`/dashboard/users` 已替换模板模拟数据，提供本部门用户、角色、状态、Clerk 绑定、Skill 权限矩阵和审计筛选，非平台管理员由服务端拒绝访问。
- 后端完整测试 133 项通过，新增跨部门管理拒绝和管理员敏感读取审计测试；本阶段 Ruff、OpenAPI 契约检查、TypeScript、定向 lint 和 Next.js 生产构建通过。构建仍保留 Google Sans Flex fallback 与 `metadataBase` 两类既有警告。
- 部署前确认没有活动 Run、Workflow Action 或执行中 Workflow。数据库与业务目录备份 `data/backups/20260814_143245_pre-stage7-user-permissions` 已通过集合和 SHA-256 回读校验，未把 `credential.key` 放入普通备份；8001 API 与 6 个 Worker 已安全重启。
- 运行态使用已绑定 Clerk 管理员会话打开用户与权限页面，正确显示 finance 部门 2 个账号，并检查管理员账号信息和员工 Skill 权限矩阵；另用本地管理员会话验证重启后的用户与审计接口及读取审计。本次未创建、禁用或修改用户，未保存权限，也未运行财务任务。

### 2026-08-14 阶段八执行记录

- FastAPI 新增独立 Skill 发布服务和管理员路由，支持服务器收件箱列表、ZIP 导入、业务元数据更新、审核、发布和历史版本回退。只有 `skill_admin` 可以访问；员工请求由服务端返回 403。
- 发布包必须包含 `tool.yaml` 和 `.release.json`。导入时限制包体积、解压体积和文件数量，拒绝越界路径、重复路径、Windows 无效路径及符号链接，并校验 Manifest、源码仓库、Commit、源码树 SHA-256、测试证据和执行入口。
- 导入后保存不可变 ZIP、包 SHA-256 和解压内容 SHA-256。审核与发布时重新计算哈希；内容被修改、测试证据无效、版本号与当前线上版本相同或目标 Skill 存在活动 Run、Workflow、Action 时拒绝切换。
- 发布与回退使用线程锁和操作系统文件锁实现跨进程串行切换；切换前自动保存当前线上版本，目录激活或 Registry 刷新失败时恢复原目录。Skill ID 与版本组合唯一，避免同一版本对应不同内容。
- Next.js 新增发布记录、收件箱、导入、元数据、审核、发布和回退的显式 BFF；管理员 Skill 页面展示受控操作区，网页不能上传或编辑代码，发布和回退必须输入完整确认文字。用户审计页增加对应中文动作名称。
- 新增单 Skill 隔离同步和发布包生成脚本。生成工具要求源码 Git 工作树干净、运行实际测试，并记录 Commit、源码树哈希、测试命令、退出码和耗时；操作步骤见 `D:\BESTEASY\financial_pj\docs\SKILL_RELEASE_WORKFLOW.md`。
- 后端全量 139 项测试通过；Ruff、OpenAPI 契约漂移检查、TypeScript、定向前端检查和 Next.js 生产构建通过。构建仅保留 Google Sans Flex fallback 与 `metadataBase` 两类既有警告。
- 部署前活动 Run、Workflow 和 Action 均为 0；`data/backups/20260814_151302_pre-stage8-skill-releases` 已完成数据库及 142 个业务文件回读校验，未包含 `credential.key`。真实 SQLite 数据库升级到 `f4a9c2e71b30`，8001 API 与 6 个 Worker 已恢复健康，19 个 Skill、0 个 Registry 错误。
- 运行态使用本地管理员会话验证登录、发布记录和收件箱接口均为 200，初始记录与收件箱均为空。浏览器无 Clerk 登录态，只验证登录组件加载；为避免重新暴露密码，没有自动填写凭据。本阶段没有导入或发布真实 Skill，没有创建任务或修改财务业务文件。

### 2026-08-14 阶段九执行记录

- 新增通用审批记录、审批接口和管理员写入审批页。发起人不能自批，审批限定本部门管理员；批准、拒绝、过期、撤销和快照失效均保留记录与脱敏审计。
- 工作流审批证据同时绑定 Skill 目录树、参数与日期、输入文件记录和磁盘 SHA-256、完整业务工作区、校验后计划、财务工作副本及变更预览。审批通过后，Worker 领取和执行写入动作前各复核一次；任一内容变化都会撤销审批并退回重新确认。
- 普通标准 Run 若 Manifest 为写入、外部动作、修改上传文件，或用户权限要求额外审批，创建端默认拒绝；历史或人工插入的同类队列任务也会被 Worker 拒领，避免绕过工作流预览。
- 新增精确域名网络策略：拒绝通配符、URL、端口、IP、localhost、重复域名和空白名单；HTTP Adapter 在请求前检查目标，子进程只接收显式网络环境，智云 Playwright 页面和 API 请求执行同一域名检查并禁止跨域重定向。当前智云仍使用内网 IP，未配置虚假域名，因此 `ar-hexiao-daily` 继续保持 `disabled`。
- 写入执行前继续校验原始输入哈希和准备快照；`apply_all.py` 完成确定性单元格写入与回读，随后更新基线并再次验证。写入阶段失败不能自动重试，批次会暂停等待管理员核对外部状态。
- 后端全量 155 项、来源 Skill 智云取数 10 项均通过；Next.js OpenAPI 契约、TypeScript、lint 和生产构建通过。仅保留既有 Starlette/httpx、Windows pytest 临时目录、嵌套组件、字体 fallback 与 `metadataBase` 警告。
- 部署前活动 Run、Workflow Action 和执行中 Workflow 均为 0。备份 `data/backups/20260814_154908_pre-stage9-approvals` 已完成数据库与 142 个业务文件回读校验，数据库 SHA-256 为 `35a6084025e3dda219e53f928f367a6b242e8e7597fb11fe90e737670b32f667`，未包含 `credential.key`。
- 真实 SQLite 数据库升级到 `a8b6d1c904fe`；8001 API 与 6 个 Worker 已恢复健康，19 个 Skill、0 个 Registry 错误，审批表初始为空，写入型 Skill 状态为 `disabled`。当前运行环境没有可用于自动会话冒烟的本地管理员明文密码，未绕过 Clerk 或新建临时账号；接口权限由完整后端测试覆盖。
- 应用内网络校验不能替代进程外限制。真实域名确认、容器或防火墙级出站隔离、PostgreSQL 并发验证和合成数据写入全流程在阶段十完成；这些验收通过前不得恢复写入型 Skill。

### 2026-08-14 阶段十 PostgreSQL 与统一部署执行记录

- 切换前确认 Run、Workflow Action 和执行中 Workflow 均为 0，并生成 `data/backups/20260814_163220_pre-stage10-postgres-cutover`；SQLite 原库保持不变，作为旧运行方式回滚点。
- 独立 Compose 项目完成 SQLite 到 PostgreSQL 16 迁移。19 张业务表、136 行记录逐表数量和规范化 SHA-256 一致，59 个 Windows 数据路径转换为容器路径，Alembic head 为 `a8b6d1c904fe`。
- 6 个并发领取线程只允许 1 个 Worker 获得全局队列锁；测试结束后探针任务为 0。生产拓扑运行 API、Next.js、PostgreSQL、2 个 Python Worker、2 个 HTTP Worker、2 个 Workflow Worker和 Caddy。
- 主机仅监听 `127.0.0.1:8443`。PostgreSQL、API、Next.js 与 Worker 不映射主机端口；Worker 只加入 `internal` 数据网络，能访问 PostgreSQL，不能解析或访问公网地址。旧 3000 和 8001 进程已停止。
- Caddy 使用本机内部 CA，同一入口提供 Next.js 与显式 BFF；未登录业务请求跳转到 Clerk 登录页，登录页返回 200。响应删除 Server、Via 和 X-Powered-By，并设置 nosniff、DENY frame、same-origin referrer 与浏览器权限限制。
- 48 个迁移文件逐一验证存在、SHA-256 一致且都位于 `/var/lib/financial-platform`。合成 `reconcile-bank` 任务 `d464cc34-2813-4590-8a6f-2cd53ba98bb3` 由 PostgreSQL Worker 成功执行，3 对 3 数据得到 2 条匹配、两侧各 1 条未匹配；输出工作簿哈希和工作表结构通过回读。
- PostgreSQL 最终备份为 `data/backups/20260814_171432_postgres-verified`，dump SHA-256 为 `34e9f450c7636c8aff18090ae29fd15d3859de85cbdfe02b24c73ba7e055b364`。恢复到临时数据库后，19 张表、150 行、迁移版本和逐表哈希一致；临时恢复库已删除。
- 回滚演练中停止容器应用，旧 SQLite API、旧 Vite 前端和 6 个 Worker 在 8001 成功恢复，健康检查和首页均为 200；随后停止旧实例并恢复 PostgreSQL 容器栈。
- 后端全量 158 项测试通过；Next.js 类型检查、lint 和生产构建通过。仅保留 5 条既有组件嵌套警告和 Google Sans Flex 回退警告，`metadataBase` 已改为 `https://localhost:8443`。
- 最终后端镜像为 `sha256:e9671b927384d1aef34467551964bd7e0f51e57de85a83fd3d92041f6a823b34`，前端镜像为 `sha256:33587fdca7b9d439cbee826714629f81fac07ec98666ed4f8ef549230390a8c1`。最终源码回滚点为 `data/backups/20260814_174307_stage10-source-rollback-final`，两个仓库的 bundle、patch 和 ZIP 均通过哈希及归档校验。
- 当前部署是本机受限试用，不是部门正式域名部署。智云仍只有 IP 地址，不能伪造域名绕过策略；在取得真实 FQDN、受信任证书、精确受控出站路径和管理员明确批准前，`ar-hexiao-daily` 继续保持 disabled。

### 2026-08-14 阶段十精确域名出站代理执行记录

- 新增 CONNECT-only 出站代理，代理容器同时加入 `data` 与 `edge` 网络；6 个 Worker 仍只加入 `internal` 数据网络，通过 `FINANCIAL_NETWORK_PROXY_URL` 把声明过网络能力的 Skill 子进程导向代理。生产白名单为空时默认拒绝全部目标。
- Skill 子进程改用最小环境，只保留操作系统、临时目录和编码必需变量，不再继承 PostgreSQL 连接串和密码、Clerk Secret 或模型 API Key。智云账号密码仍由数据库密文临时解密并通过标准输入传递，没有加入命令行或普通环境变量。
- 自动测试覆盖精确域名、子域拒绝、IP/通配符拒绝、HTTPS 443、代理地址校验、生产环境强制代理、空白名单默认拒绝和子进程密钥隔离。后端完整 184 项测试及相关 Ruff 检查通过。
- 新后端镜像为 `sha256:d485a4e81a2cbcd98c7e6fbf29f8c2115db7cc3527096b37982fd09a249a5318`。运行态中 Worker 直接连接公网返回 `Network is unreachable`，生产代理访问未批准域名返回 403；隔离临时代理只列出 `example.com` 时该主机返回 200，而 `www.example.com` 返回 403，验证后临时容器已删除。
- API、出站代理、PostgreSQL 和 6 个 Worker 均正常运行；健康接口为 production、19 个 Skill、0 个 Registry 错误。PostgreSQL 6 线程并发探针仍只有 1 个 Worker 成功领取，幂等合成任务 `d464cc34-2813-4590-8a6f-2cd53ba98bb3` 再次通过。
- 新增正式域名自动证书与公司证书两套 Caddy 模板，以及不会输出密钥的生产配置生成/校验工具。当前正式配置继续保留 localhost 和空业务白名单；真实智云 HTTPS FQDN、证书信任和现场 443 连通性未提供，因此 P2-05 保持“基础设施完成，待现场验收”，不得恢复写入型 Skill。

### 2026-08-17 Pi Agent Runtime 与执行闸门复核记录

- 新增独立 `agent-runtime` 包，使用 `@earendil-works/pi-agent-core` 和 `@earendil-works/pi-ai`；标准 AI 助手和工作流 Agent 均经 Next.js 服务端 BFF、FastAPI 权限校验和平台模型网关，浏览器不接触模型密钥、数据库连接、本地路径或 Clerk 服务端令牌。
- `/dashboard/ai-chat` 只允许已发布、标准、只读且有 `can_create_draft` 权限的 Skill；`/dashboard/workflows` 只暴露五类受控动作，Worker 仍是唯一执行者，确认按钮继续调用原有确认与审批状态机。
- 模型网关拒绝上游缓存、持久化、供应商路由和任意 provider options；SSE `text/event-stream` 已写入根 OpenAPI 契约，工作流动作请求改为按动作名区分的结构化类型。
- `FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED=false` 在生产 Compose 中默认启用，后端统一拦截工作流创建、启动、旧消息确认、批次重试、Agent 执行动作和 Worker 执行；本阶段没有启动 `ar-hexiao-daily`、访问智云、读取真实财务文件或写入工作簿。

### 2026-08-17 当前执行链调整

- 运行 Skill 不再进入管理员审批队列。新任务不会创建或强制审批记录；旧审批表、历史接口和旧状态仅保留为兼容读取，不能阻断新的 Worker 领取。写入型工作流仍需要发起人的写入确认和变更复核。
- 任务失败统一记录员工、Skill、失败步骤和脱敏原因，工作流进度卡片直接展示这些信息，避免只显示通用的 500 错误。
- `/dashboard/ai-chat` 恢复为可连续对话的模型聊天框，并提供运行中任务和指定任务状态查询工具。生产 Compose 默认 `AGENT_RUNTIME=pi`，模型密钥仍由服务端模型网关管理。
- 文件中心按 Skill 分组展示文件；运行产出使用独立文件记录，保留历史版本，不覆盖已有文件。
- Pi Runtime 6 项测试、后端完整测试、前端类型检查、OpenAPI 契约检查、Agent 事件解析、生产构建和 Compose 健康检查通过。前端严格 lint 仍只保留模板中既有的 5 条嵌套组件警告。
