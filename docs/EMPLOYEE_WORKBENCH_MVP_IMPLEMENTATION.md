# 财务工具平台员工工作台实施方案

## 1. 文档目的

本文将财务工具平台调整为“工具驱动为主，AI 辅助推荐 Skill、填写参数和解释结果，任务中心负责确认、执行和交付”的产品形态，并把改造拆解到具体代码文件、数据库对象、接口、开发任务和验收证据。

本文覆盖完整部门试用版。若要求 10 个工作日交付，应采用第 13 节定义的受限 MVP：只开放内网、只启用 3～5 个只读或生成副本的 Skill、所有任务强制确认、写入型 Skill 全部禁用。完整认证、审批、网络隔离和写入型任务预计需要 15～20 个工作日。

## 2. 产品边界

### 2.1 员工端

员工端只保留三个一级入口：

1. 我的工作台；
2. 财务工具；
3. 运行记录。

员工不接触模型供应商、模型名称、API Key、Skill SHA、entrypoint、Worker Pool、Registry 重载和运行进程等技术信息。

### 2.2 管理员端

管理员端统一放在 `/admin`，包括：

1. Skill 管理；
2. 模型连接；
3. 业务凭据；
4. 员工权限；
5. 运行审计；
6. 系统设置。

### 2.3 AI 能力边界

AI 第一版只负责：

- 从当前员工有权限的已发布 Skill 中推荐工具；
- 从自然语言中提取受 Schema 约束的参数；
- 判断缺失文件和缺失参数；
- 为员工生成不可执行的任务草稿；
- 将确定性执行结果转成业务说明。

AI 不得创建运行任务、批准任务、修改文件、计算财务金额或绕过后端校验。只有员工确认后，后端才能把任务草稿转换为真实运行任务。

## 3. 当前实现与主要差距

| 能力 | 当前实现 | 目标 | 处理方式 |
| --- | --- | --- | --- |
| 身份认证 | 浏览器发送 `X-User-*`，后端直接信任 | 服务端可信登录和会话 | P0 重做 |
| 数据权限 | 多数读取按 `department_id` 放行 | 默认只允许资源所有者 | P0 重做 |
| 文件目录 | `uploads/{file_id}`、`runs/{run_id}` | 按 `user_id/run_id` 隔离 | P0 迁移 |
| Skill 参数 | 已有 JSON Schema | 增加安全范围和 UI 描述 | 扩展 Manifest |
| 文件角色 | Manifest 已支持独立角色 | 统一任务向导按角色上传 | 直接复用 |
| 任务确认 | 普通任务已有 `waiting_confirmation` | 所有员工任务必须确认 | 收紧规则 |
| 审批 | 没有通用审批模型 | 写入任务双人审批 | P2 新增 |
| AI 参数解析 | 针对已选 Skill | 在授权 Skill 集合中推荐并生成草稿 | P1 新增 |
| 模型配置 | 员工可选择连接和模型 | 管理员配置默认模型档案 | P1 改造 |
| 审计 | 已保存运行、版本、哈希和事件 | 增加登录、权限、草稿、审批和下载审计 | P0/P2 扩展 |
| 数据库迁移 | `create_all` 加少量 SQLite 补列 | 版本化迁移 | P0 引入 Alembic |
| 网络白名单 | Manifest 可声明，执行层未形成强隔离 | 代码校验加基础设施出站限制 | P2 实施 |

当前必须视为安全阻断项：`frontend/src/api.ts` 根据 URL 生成管理员身份；`backend/app/auth.py` 信任身份请求头；文件下载、任务和工作流读取主要按部门放行；`ar-hexiao-daily` 仍为已发布、写入风险、无需确认且未配置网络白名单。

## 4. 目标架构

```mermaid
flowchart LR
    U["员工浏览器"] --> A["服务端登录会话"]
    A --> W["工作台 / 工具目录 / 运行记录"]
    W --> D["TaskDraft 不可执行草稿"]
    D --> V["权限、文件、Schema、安全范围校验"]
    V --> C["员工确认"]
    C --> R{"风险级别"}
    R -->|"只读或生成副本"| Q["Run queued"]
    R -->|"写入"| CR["变更复核"]
    CR --> AP["审批人批准"]
    AP --> Q
    Q --> WK["隔离 Worker"]
    WK --> S["确定性 Skill"]
    S --> O["结果文件、摘要和审计"]
```

核心原则：

- `TaskDraft` 与 `RunRecord` 分表。草稿永远不能被 Worker 领取。
- 确认或审批时重新校验权限、文件哈希、Skill 版本和参数，不能沿用页面缓存结论。
- 审批通过后生成不可变执行快照；参数、文件、Skill 版本或预览变化时审批自动失效。
- 员工接口不返回模型、Skill 技术字段和内部运行信息。
- 管理员跨用户读取必须有权限且写入审计事件。

## 5. 数据模型与数据库迁移

### 5.1 新增表

#### `users`

| 字段 | 说明 |
| --- | --- |
| `id` | UUID 或稳定员工 ID |
| `username` | 唯一登录名 |
| `display_name` | 页面显示名 |
| `password_hash` | Argon2 等安全哈希，禁止明文 |
| `role` | `finance_user / approver / skill_admin` |
| `department_id` | 部门 |
| `status` | `active / disabled / locked` |
| `password_changed_at` | 密码更新时间 |
| `created_at / updated_at` | 审计时间 |

#### `user_sessions`

保存随机会话令牌的哈希、用户、到期时间、最后使用时间、撤销时间和客户端摘要。浏览器仅保存 `HttpOnly + Secure + SameSite=Lax` Cookie，数据库不保存原始令牌。

#### `user_skill_permissions`

保存员工可运行的 Skill、是否允许上传、是否允许创建草稿、是否需要额外审批。默认拒绝，没有授权记录就不可运行。

#### `model_profiles`

保存管理员选择的平台默认模型档案：

```yaml
id: finance-assistant
connection_id: <管理员连接>
model: <已验证模型>
temperature: 0
response_format: json
timeout_seconds: 30
status: active
```

员工接口不得返回 `connection_id`、供应商或模型名称。

#### `task_drafts`

保存原始需求、推荐 Skill、置信度、候选 Skill、参数、文件角色、缺失项、后端校验结果、创建人、Skill 版本和到期时间。状态为：

```text
draft → waiting_input → ready_for_confirmation → converted / expired / cancelled
```

#### `approval_records`

保存运行任务的变更复核和审批记录，包括审批类型、状态、申请人、审批人、意见、执行快照哈希和时间。拒绝、撤销和重新提交都新增记录，不覆盖历史记录。

#### `audit_events`

统一记录登录、退出、登录失败、文件上传/下载/删除、草稿创建、任务确认、审批、取消、管理员查看、权限变更、模型配置变更和 Registry 操作。

### 5.2 修改现有表

`files`：增加 `draft_id`，并将磁盘存储路径迁移到用户级目录。

`runs`：增加 `created_from_draft_id`、`risk_level`、`approval_required`、`approval_state`、`execution_snapshot_hash`、`change_reviewed_by/at`、`approved_by/at`、`rejected_by/at` 和 `rejection_reason`。

`run_events`：保留业务阶段事件；技术日志另存但只对管理员或运行详情接口开放。

### 5.3 迁移文件

新增：

```text
alembic.ini
backend/alembic/env.py
backend/alembic/script.py.mako
backend/alembic/versions/20260813_01_auth_and_permissions.py
backend/alembic/versions/20260813_02_task_drafts.py
backend/alembic/versions/20260813_03_approvals_and_audit.py
backend/alembic/versions/20260813_04_user_scoped_storage.py
```

修改：

```text
backend/pyproject.toml
backend/app/database.py
backend/app/models.py
scripts/bootstrap.ps1
```

迁移要求：

- 迁移前备份 `data/financial.db` 并记录 SHA-256；
- 为现有记录创建受控的遗留所有者映射，禁止统一映射为公网共享用户；
- 文件搬迁先复制、校验哈希，再更新数据库，最后保留迁移报告；
- 迁移失败必须可回滚，不能删除原文件；
- PostgreSQL 和 SQLite 都要在测试中执行全新建库与升级路径。

## 6. 后端具体文件改动

### 6.1 身份、会话和授权

新增：

```text
backend/app/auth_models.py
backend/app/auth_service.py
backend/app/authorization.py
backend/app/routers/auth.py
backend/app/routers/admin_users.py
backend/app/schemas_auth.py
```

修改：

| 文件 | 具体改动 |
| --- | --- |
| `backend/app/auth.py` | 删除对 `X-User-Id`、`X-User-Role`、`X-Department-Id` 的信任；从安全 Cookie 解析会话；SSE 同样使用会话 |
| `backend/app/main.py` | 注册认证和管理员路由；为未登录接口返回 401；只保留 `/api/health` 为匿名接口 |
| `backend/app/settings.py` | 增加会话时长、Cookie 安全属性、登录失败阈值、反向代理可信来源配置 |
| `backend/app/models.py` | 注册 User、Session、Permission 等模型；后续可按领域拆分 |
| `frontend/src/api.ts` | 删除 `authHeaders()` 和 URL 推断角色；统一发送 Cookie；401 跳转登录页 |
| `frontend/src/types.ts` | 新增登录会话、用户、权限类型；员工类型不包含模型与技术字段 |

必须测试：伪造所有 `X-User-*` 请求头不会改变当前身份；禁用用户的既有会话立即失效；员工访问任一管理员接口返回 403。

### 6.2 用户级文件与任务隔离

修改：

| 文件 | 具体改动 |
| --- | --- |
| `backend/app/storage.py` | 上传目录改为 `uploads/{user_id}/{file_id}`；所有文件操作检查 `owner_id`；路径必须位于用户目录 |
| `backend/app/run_service.py` | `_assert_visible`、任务列表、确认、取消全部按所有者授权；文件绑定要求文件属于当前员工 |
| `backend/app/workflow_service.py` | 工作流、批次、消息、文件、结果全部按所有者授权 |
| `backend/app/main.py` | 文件下载从部门判断改为所有者判断；管理员跨用户访问写审计 |
| `backend/app/adapters.py` | 工作区改为 `runs/{user_id}/{run_id}`；传给 Skill 的身份来自服务端会话 |
| `backend/app/worker.py` | 领取任务后验证快照所有者、文件路径和审批状态 |
| `backend/app/service_credential_service.py` | 员工凭据按所有者隔离；部门共享凭据必须使用显式凭据作用域 |
| `backend/app/model_service.py` | 普通员工不再读取个人模型连接；只解析管理员启用的默认模型档案 |

新增：

```text
backend/app/resource_policy.py
backend/app/storage_migration.py
scripts/migrate_user_storage.ps1
```

### 6.3 TaskDraft 和 AI 准备接口

新增：

```text
backend/app/models_draft.py
backend/app/schemas_assistant.py
backend/app/assistant_service.py
backend/app/draft_service.py
backend/app/routers/assistant.py
backend/app/routers/task_drafts.py
backend/app/skill_policy.py
```

接口：

```http
POST   /api/assistant/prepare
GET    /api/task-drafts/{draft_id}
PATCH  /api/task-drafts/{draft_id}
POST   /api/task-drafts/{draft_id}/confirm
DELETE /api/task-drafts/{draft_id}
```

`POST /api/assistant/prepare` 处理顺序：

1. 从服务端会话取得当前员工；
2. 查询当前员工有权限的已发布 Skill；
3. 生成最小 Skill 摘要，不发送 entrypoint、Hash 或内部说明；
4. 校验请求中的文件归属；
5. 调用管理员配置的 `finance-assistant`；
6. 严格解析 JSON，不接受 Markdown 或自由文本替代；
7. 校验推荐 Skill 权限、文件角色、扩展名、大小和参数 Schema；
8. 执行 `safety_constraints` 业务范围校验；
9. 保存不可执行 TaskDraft；
10. 返回展示所需字段，不创建 Run。

返回结构：

```json
{
  "draft_id": "draft_001",
  "skill_id": "reconcile-bank",
  "skill_name": "银行流水自动对账",
  "skill_version": "1.0.0",
  "confidence": 0.96,
  "candidates": [],
  "arguments": {
    "amount_tolerance": 0.01,
    "date_tolerance_days": 2
  },
  "file_roles": {
    "bank_file": "file_001",
    "ledger_file": "file_002"
  },
  "missing_inputs": [],
  "validation_warnings": [],
  "requires_confirmation": true,
  "requires_approval": false,
  "clarification": null,
  "confirmation_text": "将按照日期容差2天进行银行流水对账。"
}
```

置信度只控制界面：`>=0.85` 展示单一推荐；`0.60～0.85` 展示最多三个候选；`<0.60` 只返回澄清问题。无论置信度多高，后端校验不能减少。

修改：

| 文件 | 具体改动 |
| --- | --- |
| `backend/app/orchestrator.py` | 保留已选 Skill 的参数解析；共享结构化模型调用与解析工具 |
| `backend/app/model_service.py` | 支持默认模型档案和结构化响应；员工请求不能覆盖模型 |
| `backend/app/schemas.py` | `RunCreate` 增加或改为只接受 `draft_id` 和幂等键；逐步弃用员工直接提交任意 Skill/参数/文件 |
| `backend/app/run_service.py` | 从已确认草稿生成 Run；事务内重新校验文件哈希、Skill 版本、权限和安全范围 |
| `backend/app/main.py` | 注册 Assistant 和 TaskDraft 路由；保留旧接口的受控兼容期 |

### 6.4 Manifest 扩展

修改 `backend/app/registry.py`，将 Manifest 扩展为：

```yaml
ui:
  employee_name: 银行流水自动对账
  short_description: 对银行流水和财务总账进行自动匹配。
  categories: [对账核对]
  estimated_minutes: 3
  output_summary: 匹配明细和待核查清单
  action_label: 开始对账
  popular: true

risk:
  level: read_only
  requires_confirmation: true
  requires_change_review: false
  requires_approval: false
  modifies_uploaded_files: false

safety_constraints:
  amount_tolerance:
    minimum: 0
    maximum: 100
  date_tolerance_days:
    minimum: 0
    maximum: 31

progress_stages:
  - key: reading_files
    label: 正在读取文件
  - key: validating_fields
    label: 正在检查字段
  - key: matching
    label: 正在匹配记录
  - key: generating_output
    label: 正在生成结果文件

result_presentation:
  metrics:
    - key: matched_count
      label: 成功匹配
    - key: review_count
      label: 待人工核查
```

需要修改每个首批上线 Skill 的 `tool.yaml`：

```text
skills/jdy-cashflow-reconcile/tool.yaml
skills/labor-invoice-check/tool.yaml
skills/receivables-merge/tool.yaml
skills/dept-expense-alloc/tool.yaml
skills/withholding-report-rename/tool.yaml
skills/ar-hexiao-daily/tool.yaml
```

若 Skill 来源由 `D:\BESTEASY\finance-skills` 同步，必须先修改来源仓库对应 `tool.yaml`，通过校验后再同步平台，避免下次同步覆盖平台配置。

### 6.5 审批和写入型任务

新增：

```text
backend/app/models_approval.py
backend/app/schemas_approval.py
backend/app/approval_service.py
backend/app/routers/approvals.py
backend/app/execution_snapshot.py
```

状态规则：

```text
只读任务：confirmed → queued → running → succeeded / failed

写入任务：confirmed
         → waiting_change_review
         → waiting_approval
         → approved
         → queued
         → running
         → succeeded / failed
```

硬性约束：

- 发起人不能审批自己的写入任务；
- 审批人必须有对应 Skill 的审批权限；
- 审批前必须存在变更预览及其 SHA-256；
- 批准后参数、文件、Skill 快照、预览任一变化，批准立即失效；
- Worker 只领取 `queued` 且审批快照匹配的任务；
- 写入任务失败后不得自动重试，必须人工确认外部状态。

修改：

```text
backend/app/models.py
backend/app/run_service.py
backend/app/scheduler.py
backend/app/worker.py
backend/app/events.py
backend/app/workflow_service.py
frontend/src/pages/RunDetail.tsx
frontend/src/pages/AdminApprovals.tsx
frontend/src/types.ts
frontend/src/api.ts
```

### 6.6 审计

新增：

```text
backend/app/audit_service.py
backend/app/routers/admin_audit.py
backend/app/schemas_audit.py
```

每条审计事件至少保存：操作者、真实服务端角色、动作、对象类型、对象 ID、结果、原因码、请求 ID、时间和必要的前后状态摘要。禁止保存密码、Cookie、API Key、业务凭据、完整财务文件内容和不必要的敏感参数。

## 7. 前端具体文件改动

### 7.1 路由与布局

修改：

| 文件 | 具体改动 |
| --- | --- |
| `frontend/src/App.tsx` | 增加 `/login`；员工路由守卫；管理员嵌套路由；删除员工 `/models` 入口 |
| `frontend/src/components/Layout.tsx` | 员工侧只保留三个入口；不再请求或展示 Worker、模型和技术状态；管理员使用独立导航 |
| `frontend/src/api.ts` | Cookie 会话；增加草稿、权限、审批、审计接口；删除身份请求头 |
| `frontend/src/types.ts` | 员工 DTO 与管理员 DTO 分离，避免前端仅靠隐藏字段 |
| `frontend/src/styles.css` | 工作台、工具卡、向导、状态和移动端样式 |

新增：

```text
frontend/src/auth/AuthProvider.tsx
frontend/src/auth/RequireAuth.tsx
frontend/src/auth/RequireAdmin.tsx
frontend/src/pages/Login.tsx
frontend/src/layouts/EmployeeLayout.tsx
frontend/src/layouts/AdminLayout.tsx
```

### 7.2 我的工作台

新增或重构：

```text
frontend/src/pages/Workbench.tsx
frontend/src/components/workbench/AssistantPrepareBox.tsx
frontend/src/components/workbench/CommonTools.tsx
frontend/src/components/workbench/PendingActions.tsx
frontend/src/components/workbench/RecentResults.tsx
frontend/src/components/workbench/CandidateTools.tsx
```

数据来源：

```http
GET  /api/workbench
POST /api/assistant/prepare
```

`GET /api/workbench` 由后端一次返回员工常用工具、待操作任务和最近结果，避免页面分别拉取全部 Skill、全部运行和全部工作流后在浏览器聚合。

### 7.3 财务工具目录

重构：

```text
frontend/src/pages/SkillList.tsx
frontend/src/components/tools/ToolCategoryTabs.tsx
frontend/src/components/tools/EmployeeToolCard.tsx
```

员工工具卡只使用白名单 DTO：名称、说明、输入材料、输出、预计耗时、风险说明和操作按钮。管理员技术字段由独立管理员接口返回。

### 7.4 统一任务向导

重构 `frontend/src/pages/SkillRun.tsx`，新增：

```text
frontend/src/pages/ToolWizard.tsx
frontend/src/components/wizard/WizardStepper.tsx
frontend/src/components/wizard/FileRoleUpload.tsx
frontend/src/components/wizard/ParameterForm.tsx
frontend/src/components/wizard/NaturalLanguageRequirements.tsx
frontend/src/components/wizard/TaskConfirmation.tsx
frontend/src/components/wizard/BusinessProgress.tsx
frontend/src/components/wizard/ResultDelivery.tsx
frontend/src/components/wizard/TechnicalRunDetails.tsx
```

页面步骤固定为：材料、要求、确认、执行、结果。文件角色严格来自 Manifest，不提供一个通用上传框猜测文件用途。技术日志默认折叠并按权限加载。

### 7.5 管理员页面

将当前 `Admin.tsx` 拆分为：

```text
frontend/src/pages/admin/AdminSkills.tsx
frontend/src/pages/admin/AdminModels.tsx
frontend/src/pages/admin/AdminCredentials.tsx
frontend/src/pages/admin/AdminUsers.tsx
frontend/src/pages/admin/AdminAudit.tsx
frontend/src/pages/admin/AdminSettings.tsx
frontend/src/pages/admin/AdminApprovals.tsx
```

模型连接页面从员工路由移到管理员路由；业务凭据的可见范围、所有者和用途必须明确。任何凭据接口只返回提示信息，绝不返回原值。

## 8. `应收核销日清` 的专项处理

### 8.1 立即措施

在通用审批完成前：

```yaml
status: disabled
risk:
  level: write
  requires_confirmation: true
  requires_change_review: true
  requires_approval: true
```

涉及文件：

```text
D:/BESTEASY/finance-skills/skills/ar-hexiao-daily/tool.yaml
D:/BESTEASY/financial_pj/skills/ar-hexiao-daily/tool.yaml
scripts/sync_finance_skills.py
backend/tests/test_skill_bridge.py
backend/tests/test_workflow.py
```

先改来源仓库，再执行单 Skill 同步；同步后验证平台仍为 disabled。不能只修改平台副本。

### 8.2 网络访问

Manifest 中加入真实业务域名之前，先用只读诊断确认实际登录、API、静态资源和重定向域名。不得填写宽泛通配符，也不得把 IP 段或任意 HTTPS 当成白名单。

需要修改：

```text
backend/app/adapters.py
backend/app/worker.py
backend/app/network_policy.py
skills/ar-hexiao-daily/tool.yaml
skills/ar-hexiao-daily/vendor/scripts/jdy_login.py
skills/ar-hexiao-daily/vendor/scripts/fetch_zhiyun.py
```

注意：Python/浏览器进程中的 URL 检查只能降低误访问，不能代替操作系统、容器或防火墙级出站控制。正式恢复写入型 Skill 前，部署环境必须提供不可由 Skill 绕过的网络出站限制；否则不能宣称 `network_allowlist` 已被强制执行。

### 8.3 恢复发布条件

- 独立账号和用户级文件隔离通过；
- 双人审批通过；
- 变更预览与执行快照绑定通过；
- 真实域名白名单和基础设施出站限制通过；
- 使用合成数据完成确认、拒绝、审批过期、执行成功和执行失败测试；
- 写后回读、幂等复核和原文件哈希保护仍通过；
- 管理员明确批准重新发布。

## 9. API 清单

### 9.1 员工接口

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/session
GET  /api/workbench
GET  /api/tools
GET  /api/tools/{skill_id}
POST /api/files
GET  /api/files/{file_id}/download
POST /api/assistant/prepare
GET  /api/task-drafts/{draft_id}
PATCH /api/task-drafts/{draft_id}
POST /api/task-drafts/{draft_id}/confirm
GET  /api/runs
GET  /api/runs/{run_id}
POST /api/runs/{run_id}/confirm-change-review
POST /api/runs/{run_id}/cancel
GET  /api/runs/{run_id}/events
```

### 9.2 审批接口

```text
GET  /api/approvals
GET  /api/approvals/{approval_id}
POST /api/approvals/{approval_id}/approve
POST /api/approvals/{approval_id}/reject
```

### 9.3 管理员接口

```text
GET/POST/PATCH /api/admin/users
GET/PUT         /api/admin/users/{user_id}/skills
GET/POST/PATCH /api/admin/model-profiles
GET/POST/DELETE /api/admin/model-connections
GET/POST/DELETE /api/admin/service-credentials
GET             /api/admin/audit-events
POST            /api/admin/registry/reload
GET/PUT         /api/admin/settings
```

员工接口和管理员接口使用不同响应模型。员工接口不得先返回技术字段再由前端隐藏。

## 10. 测试文件和验收证据

### 10.1 后端测试

新增：

```text
backend/tests/test_auth.py
backend/tests/test_user_isolation.py
backend/tests/test_task_drafts.py
backend/tests/test_assistant_prepare.py
backend/tests/test_skill_permissions.py
backend/tests/test_approvals.py
backend/tests/test_audit_events.py
backend/tests/test_model_profiles.py
backend/tests/test_manifest_ui.py
backend/tests/test_network_policy.py
backend/tests/test_database_migrations.py
```

修改：

```text
backend/tests/conftest.py
backend/tests/test_platform_e2e.py
backend/tests/test_parallel_workers.py
backend/tests/test_workflow.py
backend/tests/test_model_providers.py
```

关键安全用例：

- 员工 A 不能列出、读取、下载、绑定、删除或监听员工 B 的资源；
- 修改 URL、查询参数或 `X-User-Role` 不能成为管理员；
- SSE 不接受 URL 中声明的用户身份；
- 模型推荐未授权 Skill 时后端拒绝并记录审计；
- 文件后缀正确但内容签名不符时拒绝；
- 草稿创建后文件内容或 Skill 版本变化，确认失败；
- 写入任务未审批、审批人是发起人、审批过期或快照变化时 Worker 不领取；
- 密码、Cookie、API Key 和业务凭据不进入日志、模型上下文和任务结果。

### 10.2 前端测试

当前前端没有测试框架。修改 `frontend/package.json`，引入 Vitest、React Testing Library，并根据条件增加 Playwright 端到端测试。

新增：

```text
frontend/src/test/setup.ts
frontend/src/pages/Login.test.tsx
frontend/src/pages/Workbench.test.tsx
frontend/src/pages/ToolWizard.test.tsx
frontend/src/pages/RunDetail.test.tsx
frontend/src/pages/admin/AdminUsers.test.tsx
frontend/e2e/employee-flow.spec.ts
frontend/e2e/user-isolation.spec.ts
frontend/e2e/approval-flow.spec.ts
```

### 10.3 AI 评测

新增脱敏或合成评测集：

```text
backend/evals/assistant_prepare_cases.jsonl
backend/evals/run_assistant_eval.py
backend/evals/README.md
```

每条样例包含需求、可用 Skill、文件角色、期望 Skill、期望参数和允许误差。至少覆盖：明确需求、相似工具、缺文件、参数越界、模糊需求、恶意提示、未授权 Skill 和无匹配 Skill。

验收口径：

- Skill 推荐正确率按 top-1 统计，目标 `>=90%`；
- 参数提取正确率按字段统计，目标 `>=95%`；
- 所有越权、越界和非法模型输出必须 100% 被后端拦截；
- 评测集不得包含真实客户、账号、金额、凭据或真实财务文件。

## 11. 开发任务拆分

| ID | 任务 | 主要文件 | 前置 | 验收结果 |
| --- | --- | --- | --- | --- |
| P0-01 | 停止共享公网测试入口并禁止真实文件 | 运行配置、部署说明 | 无 | 不存在 `public-gateway-user` 可用入口；真实文件未上传 |
| P0-02 | 禁用应收核销日清 | 两处 `ar-hexiao-daily/tool.yaml`、同步脚本 | 无 | Registry 显示 disabled，无法创建任务 |
| P0-03 | 引入 Alembic 和备份流程 | `backend/pyproject.toml`、`database.py`、`alembic/*` | 无 | 新库和旧库升级测试通过 |
| P0-04 | 用户、会话和登录 | `auth.py`、auth 新模块、登录页 | P0-03 | 请求头伪造无效；会话可撤销 |
| P0-05 | 员工 Skill 权限 | permission 模型、管理员用户接口 | P0-03/P0-04 | 默认拒绝；授权后才可见可运行 |
| P0-06 | 用户级资源隔离 | storage/run/workflow/main/adapters | P0-04 | 跨用户矩阵全部 403/404 |
| P0-07 | 用户级目录迁移 | 迁移脚本、storage migration | P0-03/P0-06 | 文件哈希不变；迁移报告完整 |
| P0-08 | 统一审计基础 | audit 模型和服务 | P0-03/P0-04 | 登录、文件、权限事件可查询 |
| P1-01 | Manifest UI 与安全字段 | `registry.py`、首批 tool.yaml | P0 | Registry 校验和员工 DTO 通过 |
| P1-02 | 管理员默认模型档案 | model profile、model service | P0-04 | 员工不能选择或查看模型 |
| P1-03 | Assistant Prepare | assistant/draft/router/schema | P1-01/P1-02 | 返回受校验草稿，不创建 Run |
| P1-04 | TaskDraft 确认转换 | draft/run service | P1-03/P0-06 | 事务内复核后才创建 Run |
| P1-05 | 工作台聚合接口 | workbench service/router | P1-01/P0-06 | 常用、待办、结果只含本人数据 |
| P1-06 | 员工导航和工作台 | App/Layout/Workbench 组件 | P1-05 | 员工只有三个一级入口 |
| P1-07 | 工具目录 | SkillList/ToolCard/分类 | P1-01 | 无技术字段；分类和权限正确 |
| P1-08 | 统一任务向导 | ToolWizard 与子组件 | P1-03/P1-04 | 三步内确认常用工具 |
| P1-09 | 业务进度和结果交付 | RunDetail/结果组件 | P1-08 | 默认只显示业务阶段和摘要 |
| P1-10 | 员工运行记录 | RunList/API | P0-06 | 只显示本人记录，可重试失败任务 |
| P1-11 | AI 评测集和报告 | `backend/evals/*` | P1-03 | 推荐和参数指标达到目标 |
| P1-12 | 受限 MVP 端到端验收 | backend/frontend/e2e | P1 全部 | 只读 Skill 部门内网试用通过 |
| P2-01 | 审批数据模型和接口 | approval 模块 | P0 | 批准、拒绝、撤回完整留痕 |
| P2-02 | 变更复核与不可变快照 | run/execution snapshot | P2-01 | 快照变化导致审批失效 |
| P2-03 | Worker 审批硬闸 | scheduler/worker | P2-02 | 未批准写入任务永不领取 |
| P2-04 | 管理员与审批页面 | admin pages/API | P2-01 | 审批人可处理授权范围任务 |
| P2-05 | 网络白名单与出站隔离 | network policy/部署配置 | P2-03 | 非白名单域名在进程外被阻断 |
| P2-06 | 应收核销专项回归 | workflow/Skill/测试 | P2-03/P2-05 | 确认、审批、写后复核通过 |
| P2-07 | 恢复应收核销发布 | 来源 tool.yaml/同步/Registry | P2-06 | 管理员审批后 published |
| P2-08 | 完整部门试用验收 | 全量测试和安全检查 | P2 全部 | 满足第 14 节全部标准 |

## 12. 依赖关系和并行方式

关键路径：

```text
数据库迁移
→ 可信登录
→ 用户级隔离
→ Manifest 权限/UI 字段
→ TaskDraft/Assistant Prepare
→ 统一向导
→ 受限 MVP
→ 审批硬闸
→ 网络隔离
→ 写入型 Skill
```

前端工作台视觉开发可在接口契约冻结后与后端并行；权限、审批和 Worker 硬闸不能只做前端模拟。所有安全判断必须由后端测试证明。

## 13. 排期

### 13.1 10个工作日受限 MVP

| 工作日 | 主要工作 |
| --- | --- |
| 第1天 | 停止共享入口、禁用写入 Skill、冻结接口和 Manifest 扩展 |
| 第2天 | Alembic、用户/会话表、登录接口 |
| 第3天 | 员工权限和用户级文件/任务隔离 |
| 第4天 | 文件目录迁移、审计基础、权限回归 |
| 第5天 | 默认模型档案、TaskDraft 数据模型 |
| 第6天 | `/api/assistant/prepare` 和后端校验 |
| 第7天 | 工作台、工具目录和员工导航 |
| 第8天 | 统一任务向导和强制确认 |
| 第9天 | 运行进度、结果交付、失败重试和 AI 评测 |
| 第10天 | 全量回归、跨用户安全测试、部署和受限验收 |

这一排期要求：一名前后端均可开发的主开发者加一名测试/复核人员；首批仅 3～5 个只读或生成副本的 Skill；不开公网；不开放写入型任务；不在10天内承诺完整审批和基础设施出站隔离。

### 13.2 完整部门试用版

在受限 MVP 后增加 5～10 个工作日完成审批、不可变快照、Worker 硬闸、网络出站隔离、应收核销专项回归和完整安全验收。

## 14. MVP 验收标准

### 14.1 功能

- 员工不需要选择或查看模型；
- 员工三个步骤内可以确认一个常用工具任务；
- 工具按独立文件角色上传，不猜测文件用途；
- 待确认、变更复核和最近结果数据准确；
- 失败任务显示业务可理解的原因和受控重试入口；
- 结果页面提供摘要、结果文件和待核查明细。

### 14.2 安全

- 服务端认证身份，伪造身份请求头无效；
- 员工不能访问其他员工的文件、草稿、任务、事件或结果；
- 模型和业务凭据只在后端保存和使用；
- 所有模型输出经过权限、文件、Schema 和安全范围校验；
- 所有员工任务都经过员工确认；
- 原始上传文件不被 Skill 修改；
- 写入型 Skill 在审批功能完成前保持 disabled；
- 未经过完整部署安全验收前，真实财务文件不得通过临时公网隧道传输。

### 14.3 审计与质量

- 每个 Run 保存 Skill 版本、Skill Hash、参数、输入文件 SHA-256、操作者和确认记录；
- 写入任务额外保存变更预览、审批记录和执行快照哈希；
- AI 推荐 top-1 正确率 `>=90%`；
- 参数字段提取正确率 `>=95%`；
- 后端测试、前端类型检查、生产构建、端到端测试和迁移测试全部通过；
- 没有凭据、个人信息和真实财务内容进入测试数据、日志或提交记录。

## 15. 发布与回滚

发布前：

1. 备份数据库和文件目录并记录哈希；
2. 确认没有运行中、排队中、准备中或写入中的任务；
3. 执行迁移演练和回滚演练；
4. 使用合成数据完成员工 A/B 隔离、管理员、审批和结果下载测试；
5. 构建前端并运行后端全量测试；
6. 复核 `ar-hexiao-daily` 仍为 disabled；
7. 在内网部署并验证 HTTPS 或受控反向代理身份传递。

回滚时恢复数据库和文件目录的同一时间点备份，禁止只回滚数据库而保留已迁移的文件目录。版本回滚不得重新启用任何写入型 Skill。

## 16. 完成定义

任务只有在代码、迁移、自动测试、运行态验证和审计证据同时完成后才算完成。页面隐藏、手工演示成功或单次模型返回正确都不能替代权限测试、失败路径测试和数据库回读。

## 17. 实施进度日志

本节记录每次实施完成后在本文档中回填的完成度与证据，作为第 16 节完成定义的审计依据。状态标记：✅ 已完成 / 🟡 进行中 / ⛔ 未开始 / ⏸ 按方案暂停。

### 2026-08-13 · P0-01 ✅ 停止共享公网测试入口并禁止真实文件（完成度 100%）

**改动**：

- `scripts/start.ps1`、`scripts/serve_control.py`：默认监听地址从 `0.0.0.0` 改为 `127.0.0.1`；局域网访问必须显式 `-HostAddress 0.0.0.0`。
- `.env.example`：默认 `FINANCIAL_HOST=127.0.0.1`。
- `README.md`：局域网访问改为显式开启，并说明正式认证上线前保持默认本机监听。
- `deploy/README.md`：新增「安全禁令」小节，明确禁止公网隧道（frp/ngrok/Cloudflare Tunnel/ssh -R）传输真实财务文件，禁止创建 `public-gateway-user` 之类的共享公网入口。

**运行态验证**：

- 已停止仍在监听 `127.0.0.1:8011` 的临时 Basic Auth 反向代理进程（原 `public-gateway-user` 网关）；Pinggy 临时隧道已失效。
- 仓库内不存在 `public-gateway-user` 可执行入口，`grep` 仅命中历史上下文记录和本次禁令文档。
- 注意：平台主实例仍以旧代码运行在 `0.0.0.0:8001`（P0-04 部署重启时一并收敛为默认本机监听）。

### 2026-08-13 · P0-02 ✅ 禁用应收核销日清（完成度 100%）

**改动**：

- `backend/app/registry.py`：`RiskSpec` 扩展 `requires_change_review`、`requires_approval`、`modifies_uploaded_files` 字段（向后兼容，默认 False）。
- `skills/ar-hexiao-daily/tool.yaml`：`status: disabled`；`risk` 升级为 `write + requires_confirmation: true + requires_change_review: true + requires_approval: true`；新增 `blocked_reason` 说明恢复发布条件。
- `scripts/sync_finance_skills.py`：`manifest()` 生成器支持 `change_review/approval` 参数；`ar-hexiao-daily` 目录级清单改为 `status="disabled" + confirmation/change_review/approval=True`，保证重新同步后仍保持禁用。
- 说明：源仓库 `D:\BESTEASY\finance-skills\skills\ar-hexiao-daily` 实际不存在 `tool.yaml`（该 Skill 的 manifest 由平台同步脚本生成），因此以同步脚本作为持久来源；这一差异已记录，第 8.1 节的“先改来源仓库”在本仓库改为“先改同步脚本”。
- 测试适配：`test_platform_e2e.py` 已发布列表移除 `ar-hexiao-daily`；`test_workflow.py` 增加 `_allow_disabled_workflow_skill` autouse fixture，仅测试放开 `registry.get` 的未发布可见性，真实平台仍不可见不可建任务；多日期批次测试改为显式「确认写入」驱动（因该 Skill 现在要求确认）。

**验证**：Registry 加载无错误；`status=disabled`、`risk` 含三个新字段、`blocked_reason` 存在；普通员工可见已发布 Skill 数为 10；后端全量测试通过。

### 2026-08-13 · P0-03 ✅ 引入 Alembic 迁移与数据库备份流程（完成度 100%）

**改动**：

- `backend/pyproject.toml`：新增 `alembic>=1.14,<2` 依赖。
- 新增 `alembic.ini`、`backend/alembic/env.py`、`backend/alembic/script.py.mako`；URL 从 `backend/app/settings.py` 读取，配置文件保持 ASCII。
- 新增基线迁移 `backend/alembic/versions/20260813_ef461ad114c5_baseline_current_schema.py`：重建当前全部表。
- 新增 `backend/alembic/versions/20260813_a2b6880a030c_auth_users_sessions_permissions.py`：`users`、`user_sessions`、`user_skill_permissions`（P0-04/P0-05 模型）。
- `backend/app/database.py`：`init_db()` 改为 Alembic 驱动——全新库 `upgrade head`；既有库（有表无 `alembic_version`）先 `stamp` 到基线迁移，再 `upgrade head`，真实执行基线之后的迁移（评审后修正，见下文）。
- 新增 `scripts/backup_database.py` + `scripts/backup_database.ps1`：SQLite 在线备份 API + 目录复制 + SHA-256 manifest；`bootstrap.ps1` 先备份，再调用统一 `init_db()` 入口识别旧库并升级，避免裸 `alembic upgrade head` 在无版本旧库上重建已有表。
- 新增 `backend/tests/test_database_migrations.py`：全新库升级、真实旧库（无认证表）升级、升级/降级往返。

**运行态验证**：

- 已对真实 `data/financial.db` 执行两次备份：`p0_migration`（评审前旧格式 manifest）与 `p0_recheck`（修复后新格式，132/132 文件可定位、哈希一致，见下方评审修复）。数据库 SHA-256 `d21684e4ce7542cef4eb90bafba1a1d4b535d8c87f338a8def9dba3c2d26d793`。

### 2026-08-13 · P0-04 ✅ 用户、会话和登录（完成度 100%）

**改动（后端）**：

- `backend/pyproject.toml`：新增 `argon2-cffi>=23.1,<24`。
- 新增 `backend/app/auth_models.py`：`User`、`UserSession`、`UserSkillPermission`（迁移见 P0-03）。
- 新增 `backend/app/auth_service.py`：Argon2 密码哈希、登录失败锁定、会话创建/校验/吊销、`bootstrap_admin`。评审后调整：管理员改用独立 UUID（不再沿用 `demo-user`），并实现初始密码强制修改生命周期（见下方评审修复）。
- 重写 `backend/app/auth.py`：删除对 `X-User-*` 请求头的信任；`get_current_user` / `get_sse_user` 只从 HttpOnly 会话 Cookie 解析；未登录返回 401。
- 新增 `backend/app/routers/auth.py` + `backend/app/schemas_auth.py`：`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/session`；Cookie 使用 `HttpOnly + SameSite=Lax`，`Secure` 由环境配置。
- `backend/app/settings.py`：会话 Cookie 名、有效期、Secure、SameSite、登录失败阈值与锁定时长、bootstrap 管理员环境变量。
- `backend/app/main.py`：注册认证路由；lifespan 创建 bootstrap 管理员；`/api/session` 返回 `username`；仅 `/api/health` 匿名。
- 修正 `create_session` 后未 commit 导致会话回滚的问题。

**改动（前端）**：

- `frontend/src/api.ts`：删除 `getRole()`/`authHeaders()` 与 URL 推断角色；所有请求 `credentials: 'include'`；401 自动跳转 `/login`；新增 `api.login/logout`；`eventStreamUrl` 不再携带用户身份参数。
- `frontend/src/types.ts`：`UserSession` 增加 `username`。
- 新增 `frontend/src/auth/RequireAuth.tsx`、`frontend/src/auth/RequireAdmin.tsx`、`frontend/src/pages/Login.tsx`。
- `frontend/src/App.tsx`：新增 `/login` 路由；受保护路由包 `RequireAuth`；`/admin` 包 `RequireAdmin`；移除员工 `/models` 入口。
- `frontend/src/components/Layout.tsx`：角色改用会话；移除「模型接入」员工入口；新增退出登录按钮。

**验证**：

- 新增 `backend/tests/test_auth.py`（15 项）：未登录 401、伪造 `X-User-*` 头不改变身份、员工访问管理接口 403、错误密码与锁定、登出吊销、禁用用户既有会话失效、吊销会话被拒、SSE 忽略 URL 身份、密码不明文存储、强制改密生命周期、改密拒绝错误当前密码、普通员工改密不删除管理员一次性密码文件、CSRF 同源校验、`/docs`/`/redoc`/`/openapi.json` 需登录、生产环境强制 Secure Cookie。
- 后端全量测试 91 项通过；前端 typecheck/build 通过。
- 真实运行时冒烟（独立 127.0.0.1 端口 + 临时库，共 10 项）：匿名 `/api/skills` 401；管理员登录；`/api/session`、skill 列表、registry=19、伪造身份头无效、登出失效、`/docs` 需登录、强制改密流程、CSRF 同源校验——全部 PASS。

**完成定义核对**：代码 ✅ 迁移 ✅ 自动测试 ✅ 运行态验证（隔离实例）✅ 审计证据 ✅。
**部署状态**：⏸ 代码已完成，但主实例（`0.0.0.0:8001`）仍运行旧代码、尚未安全重启；受历史旧库迁移缺陷（已修复，见下文）影响，重启前需先执行一次受控迁移与验证。

### 2026-08-13 · 评审修复（P0 旧库迁移 / P1 备份可恢复性 / P1 初始密码生命周期 / P2 Web 安全）

针对第一轮评审逐项修复并回填证据：

**P0 · 旧库迁移逻辑（阻断项，已修复）**

- 原 `database.py` 对“有平台表但无 alembic_version”的旧库直接 `stamp head`，导致 `users` 等后续迁移从未执行，`bootstrap_admin()` 在真实旧库上会报 `no such table: users`。
- 修复：新增 `_baseline_revision()` 定位迁移链底部版本；`_upgrade_database()` 对旧库先 `stamp <基线>`，再 `upgrade head`，真实执行基线之后的迁移。
- 用真实数据库备份副本复现并验证：旧库 11 表、无认证表和版本表 → `init_db()` 后 `users/user_sessions/user_skill_permissions` 存在、当时 `alembic_version = 8dd3d2f9a6c5`、`bootstrap_admin` 成功。P0-08 新增审计迁移后当前 head 为 `c4d91f7b2e10`。
- 测试：`test_database_migrations.py` 先升级到基线构造历史结构，再显式删除 `alembic_version`，真实覆盖“有业务表、无版本表”的旧库接管分支；新增认证表、历史数据、bootstrap 及“数据库版本等于当前 head”断言。
- 注意：`8dd3d2f9a6c5_add_must_change_password` 迁移对 SQLite 增加 NOT NULL 列补了 `server_default=sa.false()`，避免已有行时报错。

**P1 · 备份清单可验证性（已修复）**

- 原 `backup_database.py` 丢失目录前缀、同名文件可覆盖，真实核查 134 个文件仅 1 个能按 manifest 定位。
- 修复：manifest 键改为相对备份根目录的完整路径（如 `uploads/<file_id>/xxx.xlsx`）；拒绝重复键；备份结束后重读全部文件并校验哈希，不一致即报错。
- 复核：`p0_recheck` 备份 132 个文件 = manifest 132 条，全部可直接定位，哈希零失配。
- 凭据密钥：默认备份**不**包含 `data/credential.key`，manifest 显式声明“仅恢复备份无法解密模型连接/业务凭据”；提供 `--include-keys` 把密钥放入独立 `credential-recovery/` 并附高敏警告，要求与主备份分开保管。
- 二次评审修复：主备份与 `credential-recovery/` 分别按各自 manifest 回读校验，避免恢复包文件被主清单误判为多余；`backup_database.ps1` 新增 `-IncludeKeys` 参数，并增加真实子进程回归测试。

**P1 · 初始管理员密码生命周期（已修复）**

- 管理员不再固定 `demo-user`，改用独立 UUID；历史演示数据归属由 P0-07 专项迁移处理。
- `users.must_change_password`：自动生成初始密码的管理员登录后被强制先改密；改密前只能访问 `/api/session`、`/api/auth/change-password`、`/api/auth/logout`，其余接口返回 `403 PASSWORD_CHANGE_REQUIRED`。
- 新增 `POST /api/auth/change-password`：校验当前密码、更新 Argon2 哈希、撤销该用户其他会话、删除一次性初始密码文件。
- 二次评审修复：只有 bootstrap 管理员处于首次强制改密状态时才删除一次性密码文件，普通员工改密不会误删管理员凭据。
- 前端：登录后若 `must_change_password` 跳转 `/change-password` 页；`RequireAuth` 对未改密用户做路由级拦截。
- 说明：Windows `chmod(0600)` 不替代 NTFS ACL，一次性密码文件在改密成功后即删除，生命周期尽可能缩短；正式部署仍建议直接配置 `FINANCIAL_BOOTSTRAP_ADMIN_PASSWORD`。

**P2 · Web 安全缺口（已修复）**

- 生产环境强制 Secure Cookie：`FINANCIAL_ENV=production` 且未开 `FINANCIAL_SESSION_COOKIE_SECURE` 时启动直接拒绝（含测试）。
- CSRF 防线：新增 `security.py` 的 `origin_guard` 中间件，状态变更请求（POST/PUT/PATCH/DELETE）校验 `Origin`/`Referer` 同源，跨源返回 403；无来源头（脚本/curl）放行，由 SameSite + 反向代理限流兜底。
- `/docs`、`/redoc`、`/openapi.json` 改为需登录，只有 `/api/health` 匿名（含测试）。
- 会话 `last_used_at` 限频刷新（300s 一次），避免前端轮询持续写 SQLite。
- 登录失败计数改为原子 `UPDATE ... SET failed_attempts = failed_attempts + 1`，避免并发丢失计数；限流仍建议在反向代理层补充。
- `.env.example` 与 `deploy/README.md` 已补充生产必填配置与说明。

**验证**：后端全量测试 91 项通过；Ruff 对 `backend/app`、`backend/tests`、`backend/alembic`、`scripts/backup_database.py` 检查通过；前端 typecheck/build 通过；真实旧库副本迁移、普通备份 132/132 回读、含密钥恢复包测试及既有运行时冒烟全部 PASS。全仓 vendor 脚本存在既有 Ruff 问题，不纳入本轮声称的检查范围。

### 2026-08-13 · P0-05 ✅ 员工 Skill 权限（完成度 100%）

**后端改动**：

- 新增 `backend/app/authorization.py`：员工 Skill 权限默认拒绝；只有存在对应 `user_skill_permissions` 记录且能力字段为 True 时才允许。`skill_admin` 按角色拥有全部 Registry 管理和使用权限，但 disabled/draft Skill 仍不能通过普通员工运行接口创建任务。
- 新增 `backend/app/routers/admin_users.py`：管理员可查询员工、创建独立账号、启用/禁用账号、替换员工 Skill 权限；创建的员工必须首次修改初始密码，禁用账号会立即撤销既有会话；禁止当前管理员禁用或移除自己的管理员角色。
- `backend/app/schemas_auth.py` 新增管理员用户和 Skill 权限 DTO；拒绝未知 Skill、重复 Skill 授权和给管理员写入多余的单项权限记录。
- `backend/app/main.py`：员工 Skill 列表只返回已发布且 `can_run=true` 的工具；未授权详情按不存在处理；参数解析、标准任务确认、工作流文件绑定、对话推进、写入确认、重建和批次重试均重新检查当前权限。
- `backend/app/run_service.py`、`backend/app/workflow_service.py`：标准任务、单个工作流和多日期批次创建均执行 `can_run` 硬闸；绑定文件时同时执行 `can_upload` 硬闸。撤权后，已经等待确认的任务不能继续执行，但员工仍可查看和取消本人已有任务。
- `backend/tests/helpers.py` 的普通业务回归账号改为显式写入测试权限，不以生产默认放行为代价维持旧测试。

**前端改动**：

- `frontend/src/types.ts`、`frontend/src/api.ts` 增加管理员用户、Skill 权限类型和管理员接口。
- `frontend/src/pages/Admin.tsx` 增加员工创建、员工选择、逐项工具授权、保存权限和账号启停界面；页面明确提示员工默认没有工具权限。

**权限接口**：

```http
GET   /api/admin/users
POST  /api/admin/users
PATCH /api/admin/users/{user_id}
PUT   /api/admin/users/{user_id}/skill-permissions
```

**验证**：

- 新增 `backend/tests/test_authorization.py` 8 项权限矩阵：无记录默认拒绝、管理员创建员工并单项授权、撤权立即隐藏、撤权阻止等待确认任务、`can_upload` 文件绑定硬闸、员工不能访问管理员权限接口、禁用账号立即撤销会话、重复授权拒绝。
- 后端全量 **99 项通过**；Ruff 指定项目代码范围通过；`git diff --check` 通过；前端 `typecheck` 和生产构建通过。
- 运行态验证使用隔离测试数据库和 FastAPI 应用生命周期，不创建真实员工、不写真实财务文件、不执行财务 Skill；真实主实例未重启，因此生产部署状态仍为“代码完成、部署未完成”。

**后续边界，不计入 P0-05 未完成项**：`can_create_draft` 已保存并可管理，将在 P1-03 Assistant Prepare 接入；`requires_approval` 已保存，将在 P2 审批硬闸接入；权限变更审计属于 P0-08。本任务没有提前伪造这些尚不存在的能力。

### 2026-08-13 · P0-06 ✅ 用户级资源隔离（完成度 100%）

**访问策略改动**：

- 新增 `backend/app/resource_policy.py`：统一所有者校验、员工列表过滤和安全目录组件校验。普通员工访问不属于自己的资源统一返回 404，避免通过响应差异确认其他员工资源是否存在；管理员仍可按本部门查看资源，用于后续运行审计。
- `backend/app/run_service.py`、`backend/app/main.py`：任务列表只返回本人任务；任务详情、确认、取消和 SSE 订阅均先校验所有者；文件下载校验所有者，并拒绝下载 `data/uploads`、`data/runs`、`data/workflows` 之外的异常路径。
- `backend/app/workflow_service.py`：工作流和批次的列表、详情、文件绑定、消息推进、确认、重建、重置和重试均经过所有者校验；文件绑定从同部门放行改为只能绑定本人上传文件。
- `backend/app/storage.py`：文件删除改为所有者校验；检查文件是否仍被使用时只扫描该文件所有者的任务和工作流，避免同部门数据互相影响。
- `backend/app/adapters.py`、`backend/app/workflow_service.py`：执行前再次校验输入文件记录属于任务所有者、类型为 input、文件存在且 SHA-256 与上传记录一致，防止绕过创建阶段直接替换绑定或文件内容。

**新数据目录**：

- 新上传文件写入 `data/uploads/{user_id}/{file_id}/`。
- 标准任务快照、输入副本、输出和日志工作区写入 `data/runs/{user_id}/{run_id}/`；Worker 与输出登记使用同一所有者目录。
- 对话工作流快照、动作工作区和产物写入 `data/workflows/{user_id}/{workflow_id}/`。
- 路径组件只允许字母、数字、点、下划线和短横线，拒绝目录分隔符及路径穿越字符。

**兼容与未完成边界**：

- P0-06 只改变访问硬闸和新写入路径，没有搬动真实旧文件。上传删除暂时兼容 `uploads/{file_id}` 旧目录，下载暂时允许三个受控数据根目录内的旧记录。
- 旧 `uploads/{file_id}`、`runs/{run_id}`、`workflows/{workflow_id}` 的物理搬迁、哈希复核、数据库路径更新和 `demo-user` 所有者映射属于 P0-07，仍未执行。
- 主实例仍是旧代码，未迁移真实库、未重启，因此本项是“代码和隔离测试完成，部署未完成”。

**验证**：

- 新增 `backend/tests/test_resource_isolation.py` 3 组跨用户矩阵，覆盖文件下载/删除，任务列表/详情/确认/取消/SSE，工作流与批次列表/详情/文件绑定/消息推进/重试，以及三类用户级目录。
- 定向资源隔离与工作流测试 11 项通过；后端全量 **102 项通过**；最终管理员部门边界调整后，资源隔离、授权和工作流 19 项定向回归再次通过。
- Ruff 对 `backend/app`、`backend/tests` 检查通过；`git diff --check` 通过（仅既有 CRLF 提示）；前端 `typecheck` 和生产构建通过。
- Pytest 退出码为 0；结束后仍出现 Windows 临时目录 `pytest-current` 清理 PermissionError，该异常发生在测试结果输出之后，不影响 102 项测试结论，但后续可单独清理本机 pytest 临时目录权限。

### 2026-08-13 · P0-07 🟡 用户级目录迁移（代码 100% · 真实迁移 0%）

**已完成的代码**：

- 新增 `scripts/migrate_user_storage.py`，以离线方式把旧目录迁移为 `uploads/{user_id}/{file_id}`、`runs/{user_id}/{run_id}`、`workflows/{user_id}/{workflow_id}`。
- 遗留所有者不会自动猜测。数据库中不存在于 `users` 表的所有者（包括 `demo-user`）必须通过 `--owner-map old=new` 显式映射到现有用户；映射同时更新 files、runs、workflow_sessions、workflow_batches、model_connections、service_credentials 的 owner_id，以及任务/工作流/批次的 owner_name。
- 实际执行前检查 runs、workflow_sessions、workflow_actions，不允许存在运行中、排队中、准备中或写入中的任务。
- `--apply` 强制要求 `--backup-manifest`；脚本会验证备份数据库哈希，并逐个确认当前 uploads/runs/workflows 文件都被该备份以相同 SHA-256 覆盖。默认不带 `--apply` 时只做预检。
- 迁移使用同盘目录 rename；每个目录搬迁后立即重读全部文件哈希。数据库路径和所有者在同一事务更新；中途失败会回滚数据库并按相反顺序搬回已移动目录。
- 报告写入 `data/migrations/user_storage_<时间>_<dry-run|applied>.json`，记录映射、资源数、文件数、逐资源哈希、路径更新数和各表所有者更新数，不记录文件内容或凭据明文。

**验证**：

- 新增 `backend/tests/test_user_storage_migration.py` 2 项：合成旧目录完成搬迁、三类文件哈希不变、数据库 owner/path 更新和报告回读；缺少遗留所有者映射或存在运行中任务时拒绝执行且目录不变。
- 迁移测试 2 项通过；加入迁移测试后，后端全量 **104 项通过**；Ruff 对后端、迁移、备份脚本和测试通过。

**部署前边界（已在下方受控部署中完成）**：

- P0-07 代码完成时尚未对真实 `data/financial.db` 和真实 uploads/runs/workflows 执行迁移，因此当时状态保持“代码完成、真实迁移未执行”。
- 随后的受控部署已按要求停止主实例、确认无活动任务、校验同一时间点备份、升级数据库、执行 dry-run 并应用迁移；`demo-user` 已明确映射给唯一 bootstrap 管理员。完成证据见“P0 受控部署”。

### 2026-08-13 · P0-08 ✅ 统一审计基础（完成度 100%）

**数据与接口**：

- 新增 Alembic 迁移 `c4d91f7b2e10_audit_events` 和 `AuditEvent` 模型，保存操作者、角色、部门、动作、资源类型/ID、结果、受限详情和时间；当前数据库 head 更新为 `c4d91f7b2e10`。
- 新增 `backend/app/audit_service.py`，统一记录与管理员查询；详情字段遇到 password、token、secret、api_key、credential、content 等敏感键时递归替换为 `[REDACTED]`。
- 新增 `GET /api/admin/audit-events`，仅管理员可访问，按当前管理员部门过滤，可按 action、actor_id 查询，单次最多 500 条。无法归属账号的匿名失败登录只保存 action/outcome，不保存尝试的用户名或密码，可供管理员看到安全事件数量。

**已接入事件**：

- 登录成功/失败、退出登录、修改密码；
- 上传文件、删除上传文件；上传审计保存文件 ID、类型、大小和 SHA-256，不保存文件名、路径或文件内容；
- 管理员创建员工、更新员工状态/角色/显示名、替换员工 Skill 权限；不保存初始密码，权限审计只保存目标用户、授权数量和 Skill ID。

**验证**：

- 新增 `backend/tests/test_audit.py` 2 项，验证成功/失败登录、文件上传删除、权限替换可由管理员查询，普通员工访问审计接口返回 403，文件名/密码不进入审计响应，敏感键递归脱敏。
- 审计、认证、权限和数据库迁移定向回归 28 项通过；Ruff 对审计模型、服务、路由、迁移和测试通过。
- 加入 P0-08 后，后端全量 **106 项通过**；Ruff 对后端、Alembic、备份与目录迁移脚本、测试全部通过。

**后续边界**：

- P0-08 是审计基础，不包含 P1 TaskDraft/AI 推荐和 P2 审批事件；这些模块实现时必须使用同一审计服务补充事件。
- 2026-08-13 受控部署后，真实运行库已包含 audit_events；P1 TaskDraft/AI 推荐和 P2 审批事件仍待对应模块接入。

### 2026-08-13 · P0 受控部署 ✅（完成度 100%）

**停机与备份**：

- 部署前只读确认没有活动 Run；唯一工作流处于 completed，两个 Workflow Action 均为 succeeded。所有遗留文件、工作流、批次、模型连接和业务凭据原 owner 均为 `demo-user`。
- 创建 `data/backups/20260813_164747_pre_p0_deploy`：数据库、31 个上传文件、84 个工作流文件、16 个日志文件全部按 manifest 回读校验，数据库备份 SHA-256 为 `d21684e4ce7542cef4eb90bafba1a1d4b535d8c87f338a8def9dba3c2d26d793`。
- 备份包含独立 `credential-recovery/` 高敏恢复包；NTFS ACL 已限制为当前 Windows 账户、SYSTEM 和本机管理员。旧实例及6个旧 Worker 已停止，确认 8001 端口释放后才开始迁移。

**数据库与目录迁移**：

- 真实数据库由11张无版本旧表迁移到 Alembic head `c4d91f7b2e10`，成功创建 users、user_sessions、user_skill_permissions、audit_events 等表。
- 创建唯一 bootstrap 管理员。由于当前没有其他真实员工账号，为避免把历史财务数据错误分配给未来普通员工，明确采用 `demo-user → bootstrap admin` 映射。
- 目录迁移 dry-run 识别32个资源目录、115个文件；使用部署前 manifest 执行 `--apply` 后，32个目录全部迁入用户级目录，115个文件哈希复核一致，45条 files.stored_path 更新完成。
- 迁移后 files 45条、workflow session 1条、workflow batch 1条、模型连接2条、业务凭据1条均归属于管理员；数据库引用的45个文件全部存在且位于 data 根目录内，不再残留旧的顶层资源目录。
- 应用报告：`data/migrations/user_storage_20260813_164859_dry-run.json`、`data/migrations/user_storage_20260813_164918_applied.json`。

**启动与运行态验证**：

- 新实例启动于 `http://127.0.0.1:8001`，不再监听 `0.0.0.0`；API 加6个 Worker（Python 2、HTTP 2、Workflow 2）共7个登记进程全部存活，health 为 ok，19个 Skill、0个 Registry 错误。
- 完成 bootstrap 管理员首次改密；一次性 `initial_admin_password.txt` 已自动删除。当前管理员密码只保存在 `data/admin_password_after_deploy.txt`，该文件设置受限 NTFS ACL，密码未写入实施文档、命令输出或审计详情；读取后应由管理员自行删除。
- 运行态冒烟14项通过：匿名 Skill、docs 和伪造身份头均被拒绝；登录/改密/新密码重登/退出有效；管理员会话有效；19个 Skill 可加载；`ar-hexiao-daily` 保持 disabled；历史工作流与历史文件可访问；审计接口可查询登录和改密事件；智云凭据记录仍配置可见。
- 第一次冒烟把一次性密码文件的整行说明误当作密码，产生一次预期的失败登录审计；未改密、未锁定账号、未创建任务或修改财务数据。修正为解析中文冒号后的密码后，14项全部通过。
- 最终回读：数据库 head `c4d91f7b2e10`、管理员 `must_change_password=0`、审计事件7条、活动 Run 0、活动 Workflow Action 0、监听地址 `127.0.0.1`、7/7进程存活。

### 2026-08-13 · P1-01 ✅ Manifest UI 与安全字段（完成度 100%）

**Manifest 与 Registry 改动**：

- `backend/app/registry.py` 新增 `ui`、`safety_constraints`、`progress_stages`、`result_presentation` 的强类型校验；已发布 Skill 在 Registry 加载时必须提供员工展示配置，分类、阶段和指标键不得重复，参数安全范围必须引用已声明参数且不得放宽 JSON Schema 范围。
- Registry 校验只作用于当前 `tool.yaml`，Worker 读取历史任务快照时仍允许缺少新增 UI 字段，避免部署后已有任务因旧快照无法反序列化。
- `RegisteredSkill.employee_dict()` 新增员工专用 DTO，只返回名称、业务说明、分类、预计耗时、输入材料、输出说明、按钮文案、风险提示、业务进度、结果指标和参数 Schema；不返回版本、状态、适配器、入口点、Worker、运行时、权限、Skill 哈希、Commit、来源、上游仓库或参数安全上限。
- `backend/app/main.py` 的 Skill 列表和详情按服务端会话角色返回数据：员工只收到业务 DTO，管理员继续收到完整技术 Manifest。权限过滤和 disabled/draft 访问规则保持不变。

**首批 Manifest 和持久化生成源**：

- `reconcile-bank`、`labor-invoice-check`、`receivables-merge`、`dept-expense-alloc`、`withholding-report-rename`、`ar-hexiao-daily`、`jdy-cashflow-reconcile` 已补齐员工展示、风险、进度和结果配置；对账金额/日期参数增加安全范围声明。
- 其余 5 个已发布 Skill（`compliance-spot-check`、`dreame-ar-progress-diff`、`order-daily-summary`、`project-detail-to-ledger`、`split-by-sales`）同步补齐必需字段，避免 Registry 因已发布 Manifest 不完整而拒绝加载。
- 所有 10 个已发布 Skill 的 `requires_confirmation` 均改为 `true`，符合“所有执行均需员工确认”的 MVP 验收条件；只读 Skill 明确声明不修改上传文件。
- `scripts/sync_finance_skills.py` 同步写入同一套 UI、进度、结果和风险字段，并保证生成的已发布 Skill 默认要求确认，防止后续同步覆盖本次配置。

**员工前端改动**：

- `frontend/src/types.ts` 增加员工展示、业务进度和结果指标类型，并把管理员专用技术字段设为可选。
- `SkillList.tsx` 使用业务分类、预计耗时和 Manifest 按钮文案，不再显示 adapter 和版本；工作流入口改用 `execution_mode`，不依赖技术 handler。
- `SkillRun.tsx`、`Dashboard.tsx`、`Layout.tsx`、`WorkflowChat.tsx` 改用员工 DTO；员工任务复核不再显示 Skill 版本、执行器、最长运行时间或模型名称，改为预计耗时、结果内容、风险和审计提示。
- 管理员 Skill 表仍显示版本、状态、执行器、来源和 Commit；员工与管理员展示边界未混用前端隐藏实现，敏感技术字段在员工 API 响应中已被后端删除。

**测试与验证**：

- 新增 `backend/tests/test_skill_manifest_ui.py`，验证 10 个已发布 Skill 均有 UI、业务进度和确认要求，首批 7 个 Manifest 配置完整，非法安全范围和未知参数引用会被拒绝。
- `backend/tests/test_authorization.py` 新增员工 DTO 禁止字段与管理员完整 DTO 用例；员工响应逐项确认不存在版本、handler、runtime、权限、哈希、Commit、来源、上游和安全上限等技术字段。
- 更新端到端测试：标准任务创建后必须处于 `waiting_confirmation`，员工确认后才进入 `queued`；并验证旧任务快照仍可由并行 Worker 执行。
- 后端全量 **112 项通过**；本任务涉及文件 Ruff 检查通过；前端 `typecheck` 和生产构建通过。Pytest 返回退出码 0 后，Windows 仍报告无权清理系统临时目录中的 `pytest-current` 链接，此提示不影响测试结果，也未触碰项目数据。

**部署证据**：

- 部署前活动 Run 0、活动 Workflow Action 0；停止旧 API 和 6 个 Worker，确认 8001 端口释放后启动新构建。
- 新实例运行于 `http://127.0.0.1:8001`，仅监听本机地址；API 和 6 个 Worker 共 7/7 个登记进程存活。
- 运行态回读：Health=`ok`、Registry Skill=19、Registry 错误=0、已发布 Skill=10、缺 UI=0、未要求确认=0；`ar-hexiao-daily` 仍为 disabled；管理员登录和退出正常。验证过程未创建任务、未上传或修改财务文件，也未输出管理员密码。

**后续边界**：P1-01 已完成并部署。员工任务页原有的模型连接加载和选择控件属于 P1-02，将在下一任务改为管理员默认模型档案；本项只删除员工 Skill DTO 和复核区中的模型名称及其他技术 Manifest 信息。

### 当前状态与后续任务

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| P0-01/P0-04 主实例部署 | ✅ 已部署 | 新代码监听 `127.0.0.1:8001`；认证、首次改密和会话撤销运行态通过 |
| P0-05 员工 Skill 权限 | ✅ 已部署 | 默认拒绝、管理员用户/授权接口、创建/确认硬闸和管理页面已在新实例生效 |
| P0-06 用户级资源隔离 | ✅ 已部署 | 文件、任务、工作流、批次和 SSE 按所有者隔离；新数据使用用户级目录 |
| P0-07 用户级目录迁移 | ✅ 已完成 | 32个资源目录、115个文件完成迁移和哈希复核；45条路径已更新，遗留 owner 映射到管理员 |
| P0-08 统一审计基础 | ✅ 已部署 | 审计迁移、脱敏服务、管理员查询及登录/文件/员工/权限事件已在真实库启用 |
| P1-01 Manifest UI 与安全字段 | ✅ 已部署 | 10 个已发布 Skill 配置完整且均需确认；员工 API 不返回技术字段；前后端与运行态验证通过 |
| P1-02 至 P1-05 | ✅ 已部署 | 默认模型档案、TaskDraft、Next.js 工作台、统一任务向导和受控 Skill 发布已接入 |
| P2-01 至 P2-04 | ✅ 已部署 | 审批记录、不可变快照、Worker 硬闸和管理员审批页面已接入 |
| P2-05 | ✅ 内网联调范围完成 | `internal` 模式已部署；只允许 `http://192.168.10.167:18880`，Worker 直连失败，精确目标返回 200，错误 IP、端口和 CONNECT 均返回 403 |
| P2-06 | ✅ 受控写入回归通过 | 2026-08-13 真实只读取数、双年度工作副本分类、写前校验、统一写入、逐格回读和写后幂等复核均已通过；原件未改 |
| P2-07 | ⛔ 尚未执行 | 需要 P2-06 回归通过并由管理员明确批准，当前继续保持 disabled |
| P2-08 | ⛔ 尚未执行 | 需要 P2-06/P2-07 完成，并使用正式平台域名、受信任证书和部门账号完成完整试用验收 |

### 2026-08-14 · P2-01 至 P2-04 应用实现与部署

- P2-01 至 P2-04 已实现并部署：审批数据模型、变更预览与不可变执行快照、Worker 双重硬闸和 Next.js 管理员审批页面均已通过测试。
- 标准写入型 Run 在没有通用预览适配器时默认拒绝，不能绕过工作流审批；写入工作流失败仍需人工核对，不能自动重试。
- P2-05 已增加 `strict` 与 `internal` 两种网络策略。当前本机部署使用 `internal`，只允许 `http://192.168.10.167:18880`；Worker 直连失败，经代理访问精确目标返回 200，错误 IP、错误端口和 CONNECT 均返回 403。验证只读取首页 HTTP 状态，未提交凭据或读取业务数据。
- 真实库已迁移至 `a8b6d1c904fe`，API 与6个 Worker 健康；`ar-hexiao-daily` 继续保持 disabled。

### 2026-08-14 · 阶段十 PostgreSQL 与容器部署

- SQLite 数据已迁移到 PostgreSQL 16，19 张业务表、136 行初始记录逐表哈希一致；合成试运行后最终备份包含 150 行，并已完成临时数据库恢复及逐表哈希验证。
- Next.js、FastAPI、PostgreSQL、Caddy 与 6 个 Worker 已运行在独立 Compose 项目。唯一主机入口为 `https://localhost:8443`；Worker 只连接内部数据网络，不能直接访问公网。
- 6 Worker 并发领取测试只产生 1 个成功领取者；旧 SQLite API、Vite 和 6 Worker 的回滚启动与再次切回容器栈均已演练成功。
- `reconcile-bank` 使用纯合成数据完成 PostgreSQL 试运行，结果摘要、输出文件 SHA-256 与工作表结构均通过回读；没有上传真实财务数据。
- 后端全量 158 项测试、Next.js 类型检查、lint 和生产构建通过。源码和数据库都已建立可回读恢复点，生产密钥未进入普通备份或源码快照。
- 出站代理、正式平台域名 Caddy 模板和生产配置校验工具均已完成。Skill 子进程使用最小环境，不再继承数据库连接串、PostgreSQL 密码、Clerk Secret 或模型 API Key。加入内网模式后，后端完整 198 项测试通过，部署后 PostgreSQL 并发探针和幂等合成任务再次通过。
- P2-05 已满足当前本机内网联调范围，P2-06 的真实取数、写入副本、写后回读和幂等复核也已完成。下一步为 P2-07 管理员恢复发布；P2-08 对外正式部署仍要求真实 FQDN、受信任证书和现场网络验收。

### 2026-08-14 · P2-05 内网精确目标联调

- 网络策略新增 `strict` 与 `internal` 模式。`strict` 保留 HTTPS FQDN:443 约束；`internal` 只接受 RFC1918 IPv4、HTTP 和显式端口，并按协议、IP、端口精确匹配。
- 当前生产配置固定为 `http://192.168.10.167:18880`，平台入口仍绑定 `127.0.0.1:8443`。代理容器连接 `data` 与 `edge` 网络，6 个 Worker 只连接 `data` 内部网络。
- 部署后验证：Worker 直连智云失败；经代理访问精确目标返回 `HTTP/1.1 200 OK`；错误 IP、错误端口和 CONNECT 均返回 `HTTP/1.1 403 Denied`。测试未使用智云账号密码，也未获取业务数据。
- 后端 198 项、相关 Ruff、Compose、生产配置、OpenAPI、Next.js 契约和类型检查通过。平台健康检查为 19 个 Skill、6 个执行容量、0 个 Registry 错误；PostgreSQL 并发探针和幂等合成任务通过。
- `ar-hexiao-daily` 继续保持 disabled。P2-06 需要使用只读智云账号完成真实取数与写入副本专项回归，并由管理员确认结果后才能恢复发布。

### 2026-08-14 · P2-06 智云真实只读取数

- 用户确认按核销日期 2026-08-13 试取数。平台从 PostgreSQL 读取唯一一条已配置凭据，在 Worker 内临时解密，并只通过标准输入交给安全取数包装器；账号和密码未进入命令行、环境变量、日志或对话。
- 取数通过内网精确目标代理完成，生成回款记录、订单交付、核销明细、订单明细和取数摘要共 5 个文件。汇总为回款记录 5 笔、22 个 SO、核销明细 22 行、订单明细 33 个 SOD；接口总数一致，缺项目交付日期、无关联订单和缺 SOD 均为 0。
- 导出版本为 `2026-08-13-flow-sales-name-v4`，摘要声明 `read_only=true`。官方来源校验脚本记录 5 个文件 SHA-256 后立即复核，全部文件未发生变化。
- 本次到取数与来源校验为止，没有执行分类、流转前置登记、日清、审批或财务工作簿写入。`ar-hexiao-daily` 继续保持 disabled；P2-06 仍缺受控写入副本专项回归。

### 2026-08-14 · P2-06 受控写入副本专项回归

- 使用用户提供的 2025、2026 两份年度盈亏核算表和一份 2026 年到账流转表建立独立工作区；三个下载原件只读，复制前后 SHA-256 完全一致。年度盈亏输入调整为数量不限、每年一份，并允许同时上传往年表；平台执行上下文保存完整年度映射，分类、校验和写入均显式传递全部年度文件。重复年份会拒绝执行。
- 2026-08-13 分类结果为 9 条可写、1 条挂账、0 条异常；写前校验为可写 9、幂等跳过 0、冲突 0。9 条目标均按智云项目交付日期进入 2026 年工作副本，2025 年工作副本未发生业务写入。
- 流转计划为自动 2、手填 3、跳过 0。统一写入前的 2 条前置登记已完成；盈亏副本写入 9 条，脚本逐格回读全部一致，流转状态阶段没有额外变更。
- 写后重新分类得到 `OK_ALREADY_SETTLED=9`；新写前计划为可写 0、幂等跳过 9、冲突 0。再次执行统一写入时三个业务工作簿 SHA-256 全部不变，幂等复核通过。三个下载原件的 SHA-256 仍与回归前一致。
- 严格轻量审计没有发现新增的文件结构错误；三份结果只报告原件中已经存在的透视表部件告警，2025 年表另有原件既有的外部链接告警。到账流转表可由 artifact-tool 正常导入和渲染；两份大型盈亏表因公式和结构复杂在 300 秒内未完成 artifact-tool 渲染，业务有效性以 OOXML 审计、写前指纹、逐格回读和写后幂等结果为准。
- 回归工作区为 `data/controlled-tests/p2-06-write-copy-20260813-20260814T112935Z/工作区`。P2-06 已完成；`ar-hexiao-daily` 仍保持 disabled，等待 P2-07 管理员明确批准恢复发布。
- 平台工作流专项 10 项和后端全量 200 项测试通过，Ruff 与差异检查通过。后端/API/出站代理/6 个 Worker 已切换到镜像 `sha256:93b44cccfc6d4aacfd1f26286dc1ba4f04601b1238a6fce841277e76f324c665`；API 健康检查为 19 个已发布 Skill、6 个执行容量、0 个 Registry 错误，登录页返回 200。
