# 项目上下文

## 2026-09-05 · 应收核销主流程测试与本机启用

- 用户明确授权先测试并启用主流程，高级关联恢复后做。本轮测试授权覆盖默认禁测约定，不修改 AGENTS.md；其他后续任务继续遵守原约定。
- 本机开发平台已启用 `ar-execution-v2`，Skill 仍为 1.6.21，新任务默认 Workflow，Pi Harness 保留可选；旧任务保持固定快照。14 个阶段包括首次分类、逐单依据、写前日清、盈亏/流转写入、写后复核、挂账重扫、最终报告、发布及正式台账登记。
- 两种模式分别以 9 月 3 日真实快照在独立库和副本上完成 14 阶段验收。Pi 使用模拟 Agent 请求，未调用真实模型；原件均未改变。后端 58、业务回归 70、前端相关测试 26、Agent 测试 7 项通过，类型检查、前端构建及新镜像能力检查通过。
- 开发 API、全部相关 Worker、代理和本机前端已更新；真实环境回读到新契约、默认方式及快照。当前材料 9 份 SHA 不变，无活动核销动作；暂存自动维护配置为 0。未连接智云或执行真实财务任务，未提交或推送。
- 真实模型容量/耗时、浏览器可视化端到端、多日/空日新版全流程及高级恢复尚未验收。详见 `.scratch/ar-agent-execution-redesign-20260905/mainflow-acceptance.md`；下方旧记录中的未部署、未测试说明属于此前切片。

## 2026-09-05 · 架构审查修复后的当前源码说明（未部署）

- 当前前端唯一维护位置是 `web/` 下的 Next.js 应用，使用 Clerk 与服务端 BFF；`frontend/`
  只出现在早期迁移记录，不是当前源码目录。FastAPI 继续位于 `backend/`，生产页面由 Next.js
  容器提供。
- 平台认证按显式 `session`、`hybrid` 或 `clerk` 模式执行；Clerk 只提供外部身份，平台本地
  用户记录承载角色、部门和 Skill 权限。Workflow 和 Pi Harness 在真正执行前都会重新核验
  任务所属用户的账号、部门和 Skill 权限；普通任务继续沿用标准任务自身的创建、领取和执行规则。
- 应收核销取数使用版本化 Fetched Bundle 契约；任务创建时固定执行方式、Skill 快照、业务日期
  和材料版本。模型可见的任务上下文、取数预览、文件页和工具结果共用结构解析、脱敏和分页边界。
- Workflow 与 Pi Harness 都由后端状态机和确定性 Worker 执行财务计算及工作簿修改。多日期任务按
  日期升序串行处理，前一天写入并回读成功后才允许下一天使用新材料版本；隔离副本、写前校验、
  回读和发布规则保留，写入失败或租约中断不自动重试。
- 工作台、任务中心和运行观测按普通任务、独立核销日期任务及核销批次统一计数，批次子任务不重复
  计算；响应会标明时间范围和用户或部门范围。任务、文件和审计查询使用服务端筛选与分页，历史
  文件引用缺失时按保守规则保护删除。
- 本轮只修改源码和必要文档，未执行测试、真实财务任务、智云取数、财务写入、权限修改、数据库
  迁移、部署、重启或 Git 发布。

## 2026-08-31 · 本机 Codex 开发 Skill 配置（历史记录）

以下十个 Skill 的名单及验证结果仅记录当时配置，已被后续固定的 26 项名单替代。当前规则以 `.codex/config.toml` 为准，文件职责及维护方式见 `.codex/README.md`；本段不作为当前启用名单或验证结果。

- 本机项目配置位于 `.codex/config.toml`，用法见 `.codex/README.md`。仅为财务平台项目启用 ask-matt、code-review、diagnosing-bugs、browser:control-in-app-browser、codebase-design、tdd、ui-ux-pro-max、domain-modeling、chrome:control-chrome、design-taste-frontend 十个 Skill。
- 默认先读取 ask-matt 判断流程，再按任务需要选择其余九个；不要求用户每次输入 `$ask-matt`，不每轮运行全部十个，不自动启用 ask-matt 引用的名单外 Skill。此设置不改变平台网页中的业务 Skill 或其运行权限。
- 已验证 TOML 可解析、十个启用路径及154个停用路径均存在、没有目录联接引起的启停冲突；全局配置、父项目配置及 ask-matt 原文件哈希保持不变，未重启业务服务或执行财务任务。
- 重启 Codex 后，在工作目录为 `D:/BESTEASY/financial_pj` 的新任务中检查实际发现结果；本次未声称旧会话已热加载配置。浏览器插件路径绑定当前版本，升级后需重查；新安装的名单外 Skill 不自动获得使用授权。
- `.codex/` 被仓库现有规则忽略，因此配置只保存在本机，不随 Git 自动分发。

## 项目目标

部门内部财务 Skill 运行平台。员工从网页选择已发布 Skill，上传文件并用自然语言描述要求；大模型只负责参数理解与结果解释，确定性脚本、RPA 或内部 API 负责真实执行。

## 权限约定

- `finance_user`：运行所有已批准的 Skill、上传和下载本部门文件、确认和取消任务。
- `skill_admin`：除普通权限外，可刷新、维护和发布 Skill。
- 写 ERP、提交凭证、付款、外发等高风险动作需要运行前确认；只读分析可直接执行。

## 技术结构

- `backend/`：FastAPI、SQLAlchemy、SQLite、Registry、Orchestrator、Worker 与适配器。
- `web/`：Next.js、React、TypeScript、shadcn/ui 与 Clerk 用户界面；通过服务端 BFF 调用平台 API。
- `skills/`：平台托管 Skill；当前 Registry 共登记 19 个，其中 10 个 published、
  1 个 draft、8 个 disabled。状态和用途明细见 `docs/FINANCE_SKILLS_CATALOG.md`。
- `data/`：上传、运行快照、输出、日志和数据库，不进入 Git。
- `docs/`：架构与 Skill 接入协议。
- `scripts/`：初始化、启动和停止脚本。
- 模型接入：普通用户可在前端只输入 API Key，后端自动验证百炼并读取支持
  Tool Calling 的千问模型；API Key 加密存放在 SQLite，主密钥位于
  `data/credential.key`，前端只显示脱敏提示。
- 任务模型：用户可在每次 Skill 运行时选择连接与模型，运行审计保留供应商和模型名。

## 2026-08-17 · Pi Agent Runtime

- 当前 Next.js 用户界面位于 `web/`，通过服务端 BFF 使用独立的 `agent-runtime/`；运行时依赖 `@earendil-works/pi-agent-core` 和 `@earendil-works/pi-ai`，不引入 `pi-coding-agent`。
- 普通 AI 助手只加载当前用户可创建草稿的已发布、标准、只读且不修改上传文件的 Skill；工作流 Skill 不进入普通 Agent 目录。
- 模型密钥由 Python `/api/assistant/model` 网关按部门连接解密和调用，Pi、浏览器和审计记录只保留连接、模型、状态、耗时和 Token 等非敏感信息。
- 工作流 Agent 只能请求阶段查询、日期设置、日清准备、重新生成和用户确认；动作仍由 FastAPI 校验并交给现有 Workflow/Worker。`ar-hexiao-daily` 当前只做合成和只读验证，不执行真实智云取数或工作簿写入。
- 工作流 Agent 页面位于 `/dashboard/workflows`，创建会话不会直接启动 Worker；页面确认按钮只把用户确认交给平台原有状态机。
- 生产 Compose 默认 `AGENT_RUNTIME=pi`，只有灰度旧实现时才设置 `AGENT_RUNTIME=legacy` 并用
  `AGENT_RUNTIME_PI_USERS` 按 Clerk User ID 选择 Pi；Pi 尚未产生文本或业务工具事件时才允许回退旧实现。
- 新任务不再等待管理员审批；工作流失败会在进度卡片中显示员工、Skill、失败步骤和脱敏原因。
  文件中心按 Skill 分组展示运行产出，每次产出创建独立文件记录并保留历史版本。

## 界面约定

- 默认采用浅色企业财务工作台：蓝色主操作、绿色安全/成功状态、浅灰页面背景。
- 桌面端使用固定侧栏；移动端使用抽屉导航，页面不得产生横向滚动。
- 所有异步数据先展示加载状态，禁止在接口返回前误显示“0 条”或空状态。
- 保留键盘焦点、跳转主内容入口、44px 触控区域和 reduced-motion 支持。

## 本地命令

```powershell
.\scripts\bootstrap.ps1
.\scripts\start.ps1
.\scripts\stop.ps1
```

测试与质量检查：

```powershell
.\.venv\Scripts\python.exe -m pytest backend
.\.venv\Scripts\python.exe -m ruff check backend skills --config backend\pyproject.toml
Set-Location web
corepack pnpm typecheck
corepack pnpm build
```

## 当前边界

本轮源码改动尚未部署。当前代码目标运行形态使用 Clerk/服务端会话混合认证、用户级资源隔离、统一审计和受控 Skill 版本发布；SQLite 适合当前单部门受限验证。进一步扩大使用范围前仍需要公司 SSO、PostgreSQL、独立隔离 Worker、病毒扫描、日志脱敏和完整备份策略。

## 2026-08-13 · 员工权限与用户级资源隔离

- P0-05 员工 Skill 默认拒绝、管理员账号/授权接口和创建及确认阶段权限硬闸已部署。
- P0-06 已把员工文件、标准任务、SSE、工作流和批次访问从同部门范围改为本人所有者范围；跨用户资源按不存在返回，运行态已部署。
- 新上传、标准任务和工作流分别使用 `uploads/{user_id}/{file_id}`、`runs/{user_id}/{run_id}`、`workflows/{user_id}/{workflow_id}`；执行前复核文件所有者、类型、存在性和 SHA-256。
- P0-06 阶段后端全量102项、Ruff、前端 typecheck/build通过；之后已在P0-07完成真实旧目录迁移。
- P0-07 离线迁移工具和合成测试已完成并用于真实迁移：执行时提供了已校验备份 manifest、显式 `demo-user → bootstrap admin` 映射且平台无活动任务；32个目录、115个文件迁移通过。
- 加入 P0-07 后，后端全量 104 项通过；前端没有新增改动，沿用本轮已通过的 typecheck/build 结果。
- P0-08 已新增并部署 audit_events 迁移、统一脱敏审计服务和管理员查询，接入登录、改密/退出、文件上传删除、员工与 Skill 权限事件；审计相关定向回归28项通过。
- 加入 P0-08 后，后端全量 106 项和项目范围 Ruff 通过。
- P1-01 已完成并部署：Registry 支持员工 UI、参数安全范围、业务进度和结果展示配置；10 个已发布 Skill 均补齐配置并要求执行前确认。员工 Skill API 已删除版本、handler、runtime、权限、哈希、Commit、来源和安全上限等技术字段，管理员仍可查看完整 Manifest。
- P1-01 验证：后端全量 112 项通过，本任务 Ruff、前端 typecheck/build 通过；运行实例保持 `127.0.0.1:8001`，Health 正常、19 个 Skill 零 Registry 错误、7/7 进程存活，`ar-hexiao-daily` 仍为 disabled。下一任务为 P1-02 管理员默认模型档案。

## 2026-08-14 · P1-02/P1-03 AI 助手与 TaskDraft

- 新增部门级 `model_profiles` 和用户级 `task_drafts`，Alembic head 为 `d7e5a3f91c42`。管理员可以从本部门已连接模型中选择助手默认模型，普通员工只能读取是否已配置。
- 助手只接收当前用户已授权、已发布、标准、只读且不修改上传文件的 Skill 安全目录；文件仅以临时别名发送。模型结构化推荐经过参数、安全范围、文件角色、格式、大小、所有权和 SHA-256 校验后保存为不可执行草稿。
- 草稿确认前重新校验权限、Skill 版本和哈希、文件记录及磁盘哈希，确认成功才创建 Run；写入、外部动作和需审批 Skill 当前被拒绝。草稿所有权隔离和确认幂等已覆盖测试。
- 后端完整测试 131 项通过，本轮 Ruff 通过；OpenAPI 契约已同步到 Next.js，前端契约检查、类型检查、定向 lint 和生产构建通过。
- 部署前没有活动任务。备份工具修复 Windows 长路径复制和校验，`data/backups/20260814_140409_pre-stage6-assistant-verified` 已校验数据库及 142 个业务文件。真实库升级后，8001 API 和 Python/HTTP/Workflow 各 2 个 Worker 均恢复健康。
- 现有 Clerk 管理员登录态已打开中文 AI 助手页面，两个模型连接及模型列表正常显示且无控制台错误。因存在两个可用连接，未替管理员选择默认模型；未调用真实模型或创建任务。

## 2026-08-14 · Next.js 迁移阶段七用户、权限与审计

- 管理员用户列表、创建、更新和 Skill 权限替换已集中到 `backend/app/admin_user_service.py`，统一限制在当前管理员所属部门。跨部门用户不进入列表，修改和授权返回不存在，不能创建其他部门账号；当前管理员不能禁用自己或移除自己的管理员角色。
- 平台固定角色仍为 `finance_user` 和 `skill_admin`。管理员默认管理当前部门全部 Skill，员工继续默认拒绝，只能获授已发布 Skill 的 `can_run`、`can_upload`、`can_create_draft` 和 `requires_approval`。Clerk 映射字段可以由平台管理员维护，但 Clerk 角色不参与平台授权判断。
- 管理员读取用户列表和审计列表现在也写入脱敏审计，审计查询增加字段长度与最多 500 条限制。新增跨部门隔离和敏感读取审计测试，后端全量 133 项通过，本阶段 Ruff 通过。
- Next.js 新增用户、更新、权限替换和审计查询显式 BFF，`/dashboard/users` 提供本部门用户、账号状态、角色、Clerk 绑定、Skill 权限矩阵和脱敏审计；OpenAPI 契约、TypeScript、定向 lint 和生产构建通过。
- 部署前确认没有活动 Run、Workflow Action 或执行中 Workflow；`data/backups/20260814_143245_pre-stage7-user-permissions` 已校验数据库及业务文件，且未包含高敏 `credential.key`。8001 API 与 6 个 Worker 已重启并通过健康检查。
- 已绑定 Clerk 管理员会话成功打开用户与权限页，显示 finance 部门 2 个账号，并检查管理员信息和员工权限矩阵；本地管理员会话验证用户和审计接口及读取审计。本次未创建、禁用或修改用户，未保存权限，未运行财务任务。

## 2026-08-14 · Next.js 迁移阶段八 Skill 版本发布

- 新增 `skill_releases` 表和受控发布服务，Alembic head 为 `f4a9c2e71b30`。只有 `skill_admin` 可以从服务器收件箱导入 ZIP、编辑业务元数据、审核、发布和回退；网页不能上传或修改代码。
- 导入限制 50 MB 包、200 MB 解压内容和 2000 个文件，拒绝越界、重复、Windows 无效路径和符号链接；校验 Manifest、源码仓库、Commit、源码树哈希、测试证据和执行入口。
- 包 SHA-256 与解压内容 SHA-256 在审核和激活时重新计算。发布/回退前检查活动 Run、Workflow 和 Action，跨线程及进程串行切换目录，Registry 加载失败时恢复原版本。
- `scripts/sync_finance_skills.py` 支持单 Skill 隔离同步；`scripts/stage_skill_release.py` 只接受干净 Git 源码仓库并运行实际测试。操作步骤记录在 `docs/SKILL_RELEASE_WORKFLOW.md`。
- 后端全量 139 项测试、Ruff、OpenAPI 契约检查、Next.js TypeScript、定向前端检查和生产构建通过。
- 部署前活动任务为 0；`data/backups/20260814_151302_pre-stage8-skill-releases` 已校验数据库及 142 个业务文件，未包含 `credential.key`。真实库升级后，8001 API 与 6 个 Worker 健康，19 个 Skill、0 个 Registry 错误；管理员登录和发布列表/收件箱接口均为 200。本阶段没有导入或发布真实 Skill。

## 2026-08-13 · P0 新代码受控部署

- 部署前确认无活动任务；创建并校验 `data/backups/20260813_164747_pre_p0_deploy`，数据库及131个目录文件均在 manifest 中通过回读，高敏凭据恢复包已限制 NTFS ACL。
- 旧实例停止后，真实数据库从无版本11表升级到 Alembic head `c4d91f7b2e10`；创建 bootstrap 管理员，将唯一遗留所有者 `demo-user` 显式映射给该管理员。
- 用户级目录迁移完成：32个资源目录、115个文件哈希一致，45条文件路径更新；45条文件记录、1个工作流、1个批次、2个模型连接和1个业务凭据均归属管理员，数据库引用文件无缺失。
- 新实例运行于 `127.0.0.1:8001`，API和6个 Worker共7个进程存活；health ok、19个 Skill、0个 Registry 错误，`ar-hexiao-daily` 保持 disabled。
- 运行态冒烟14项通过，覆盖匿名/伪造身份拒绝、首次改密、会话、历史文件和工作流、审计、凭据状态及重新登录。没有创建或执行财务任务。
- 管理员当前密码保存在受限 ACL 文件 `data/admin_password_after_deploy.txt`，未写入文档或日志；读取后应删除该文件。一次性初始密码文件已自动删除。

## 2026-07-28 · 写入后源文件校验修复

- `apply_confirmed` 现在先使用准备阶段快照执行写入前校验，再运行统一写入。
- 两份计划内工作簿均写入并通过脚本回读后，重新记录最终基线并立即复核，避免
  盈亏表写入后的中途快照把随后写入的到账流转表误判为外部改动。
- 写入后基线更新失败使用独立错误状态，页面会明确提示不要重复确认或重出日清，
  避免二次写入。
- 已恢复任务 `716f38e8-0018-4570-874a-d7621d6735a6`：跑批台账证明盈亏和
  流转均已写入，恢复过程只更新基线和任务产物登记，没有再次运行统一写入。

## 2026-07-28 · 流转清单空单号诊断

- 某条 E5 部分回款记录在分类器的 AR 总额差异分支提前生成挂起项，未把该记录
  已解析的 SO 传入结果，导致 `so_count=0`、`order_suggest=""`。
- 后续规则仍把 E5 视作可更新，因此流转计划只写“是否更新应收款=是”，不写单号；
  清单出现“自动、全部已更新”但单号为空，属于分类结果字段丢失，不是正常业务口径。
- 本次仅完成只读诊断，尚未修改 Skill 或重跑历史任务。

## 2026-07-28 · 输出文件过多诊断

- 准备阶段先把《核销日清》登记为下载产物；确认写入后，平台又把工作区
  `02_我的表副本` 和 `04_产出` 下所有 xlsx/json/txt 文件全部登记。
- 因此《核销日清》重复出现，同时用户界面暴露了写入计划、判定结果、源文件清单、
  运行报告等内部审计/中间文件。
- 本次只完成原因确认；后续应改成“用户交付文件白名单 + 日清去重”，内部文件保留
  在工作区和审计记录中，不放入普通下载列表。

## 2026-07-28 · Skill 与人工到账流转表对比

- 只读比较 Skill 产物与人工版本：两表均为 `Sheet1!A1:N110`，行身份、基础数据和
  公式完全一致；104/109 条数据行完全相同。
- 数据差异只有 5 行、6 个单元格：单号 4 处、是否更新应收款 2 处；其中一行只是
  同一组 SO 的排序和分隔符不同，没有业务差异。
- 两处确认是分类器提前返回造成 SO 丢失：E5 的 AR 级金额差异分支和 E_FEE 手续费
  分支均在逐 SO 展开之前生成挂起项。
- 另两类差异来自处理口径：Skill 只纳入当前核销日，人工版本包含历史核销信息；
  Skill 将可拆行的 E5 视作已更新，而人工版本按累计处理情况填“部分”。
- 人工版本还更新了一条不在本批智云回款记录中的历史行；Skill 按本批输入不会触碰。
- 人工版本有一处红色待办标记，Skill 的流转写入器目前只写单号和状态值，不写颜色。

## 2026-07-28 · finance-skills 批量接入

- 从 `D:\BESTEASY\finance-skills\skills` 安全同步其余 17 个 Skill，源仓库只读，
  不提交或覆盖其中的用户改动。
- 8 个成熟离线脚本通过统一桥接协议发布；加上原有 `reconcile-bank`，
  普通用户当前可运行 9 个工具。
- 同步包排除 `工作区`、测试、缓存、历史输出、`config.local*` 和凭据；
  运行不依赖源仓库或 GitHub 在线状态。
- Registry 哈希覆盖整个 Skill 包，而不再只哈希 manifest 和入口脚本；
  任务输入副本保留原文件名信息，多版本输入支持最小文件数校验。
- `ar-hexiao-daily`、金蝶 RPA 和文档/Agent 基础能力已登记但未伪装成可运行工具；
  其中现金流量核对需先修复“会计期间”分组口径。
- Python 依赖新增 pandas、xlrd、pdfplumber、requests；本机已通过清华镜像安装。
- RPA Worker 由 `FINANCIAL_WORKER_POOLS` 控制；批量接入阶段未默认启用 RPA。

## 2026-07-28 · 对话式工作流执行器

- 新增 `WorkflowSession`、`WorkflowMessage` 和 `WorkflowAction`，会话、消息、
  人工确认及后台动作均可审计。
- `workflow` 适配器不接受一次性 `/api/runs` 调用；前端从 Skill 页面创建会话，
  在专用对话页完成日期确认、文件上传、日清检查和写入确认。
- 模型只在当前阶段的 Tool Calling 白名单内选择动作；模型不可生成命令、路径、
  金额或客户明细，模型不可用时退回本地受限意图解析。
- `ar-hexiao-daily` 已发布。日期确认和《核销日清》二次确认是后端硬闸；
  未上传至少一份智云导出及两份财务工作簿时不能生成日清。
- 工作流按任务固化 Skill 快照，固定执行原 Skill 的核验脚本链；真实写入前再次
  校验阶段，并在完成后回读来源哈希。
- 默认 Worker Pool 已改为 `python,http,workflow`；RPA 仍未默认启用。
- 后端 6 项测试通过，包含完整对话状态机和越权确认测试；前端 typecheck/build
  通过。

## 2026-07-28 · 空日期状态提示修复

- 修复 `_status_reply` 构造状态字典时提前计算空日期文本，导致新会话返回
  `Invalid isoformat string: ''` 的问题；日期标签现在对未确认状态安全降级。
- “昨天”和明确日期等确定性指令改为本地规则优先，只有未命中明确意图时才交给
  模型 Tool Calling，避免模型把日期误判为“查看状态”。
- 增加“未确认日期时点击上传好了”的回归测试，确保只提示先确认核销日期。

## 2026-07-28 · 工作流自然多轮对话

- 千问不再只是强制 Tool Calling 路由器：`tool_choice` 改为 `auto`，普通问题直接
  返回自然语言，明确要求推进任务时才选择当前阶段允许的工具。
- 每轮请求携带稳定系统规则、结构化阶段/日期状态及最近 20 条用户和助手消息；
  完整历史仍由 `WorkflowMessage` 持久化，任务完成或取消后也可继续问答。
- 本地规则继续优先处理明确日期和明确动作，但“为什么不能开始”“确认写入是什么意思”
  等问句不会误触发执行；写入确认仍由后端检查当前阶段和最新用户原话。
- 前端输入框改为通用对话提示，执行期间及任务结束后仍可发送消息。
- 后端 8 项测试、前端 typecheck/build 通过。

## 2026-07-28 · 智云自动取数与加密凭据

- `ar-hexiao-daily` 升级至 1.1.0，取消“智云核销导出”手动上传项；员工只需
  上传盈亏表和到账流转表副本。
- 新增通用业务系统凭据表和 `/api/service-credentials/{service}` 接口。智云
  账号、密码使用 `data/credential.key` 加密保存，接口只返回脱敏账号；明文不进入
  Workflow 消息、Action JSON、模型上下文、命令行、环境变量或日志。
- 对话任务右侧新增“智云自动取数”卡片，可保存或更新凭据。缺凭据、缺两份财务
  工作簿或未确认核销日期时，后端硬闸均禁止排队。
- `prepare_worklist` 现在先通过标准输入调用 `fetch_secure.py`，使用本机 Edge
  登录智云并按核销日期只读获取四件套，再执行 inspect、来源快照、判定、校验、
  流转计划和日清生成。同步脚本会持续覆盖该平台安全包装器。
- 后端 9 项测试通过，新增凭据密文、响应脱敏、动作不含凭据及“先取数后分析”
  顺序测试；前端 typecheck/build 和 Skill quick_validate 通过。
- 已按当前员工保存一份智云加密凭据。内网登录页可访问，但用户要求先停止真实
  登录测试，因此没有继续验证会话 Cookie，也没有抓取任何财务数据或写智云。

## 2026-07-28 · 上传文件删除

- 普通 Skill 上传卡片和对话式工作流文件列表均新增单文件删除按钮；删除后同时
  移除前端状态、当前工作流绑定、数据库文件记录和 `data/uploads` 中的上传副本。
- 对话式工作流允许逐个上传和逐个删除，即使暂时低于 `min_files` 也可保存当前
  列表；真正生成日清前仍由后端最低文件数硬闸阻止执行。
- 文件被运行任务、当前工作流或 queued/running Action 引用时，直接删除接口返回
  409；前端先解除当前工作流绑定再删除。正在生成日清或写表时禁用上传和删除。
- 删除权限限定为上传人或管理员，输出结果不能走上传文件接口删除，存储路径必须
  严格位于对应的 `data/uploads/<file_id>` 目录。
- 后端 10 项测试通过，覆盖未绑定文件物理删除、跨用户拒绝、已绑定文件拒绝及
  材料不足时不执行；Ruff、前端 typecheck/build 通过。

## 2026-07-28 · 远程原版 ar-hexiao-daily 隔离复跑

- 刷新 `finance-skills` 的 `origin/main` 后，确认远程提交为
  `3a642d4ed34923fdb833b243a9f368d3ad1c5e6d`；因工作树存在其他本地文件，
  本次从该远程提交单独归档 `skills/ar-hexiao-daily`，未直接使用工作树版本。
- 隔离运行目录：
  `D:\BESTEASY\financial_pj\.codex\remote-skill-run-20260728_151607`。
- 使用 2026-07-27 同批智云四件套及写入前的到账流转表、盈亏核算表备份，
  仅运行至人工确认硬闸，生成
  `工作区\04_产出\核销日清_20260727.xlsx`，未调用任何 apply/write 脚本。
- 结果汇总：到账 12 笔、订单行 20 条；今天要填 13、挂账待办 6、异常 1；
  流转计划为自动写 6、须手填 6、跳过 0。
- `verify_sources.py verify` 通过，7 个源文件与运行前指纹一致；两张工作簿副本
  SHA-256 仍分别为 `49BE141D...CFF0CB` 和 `CE9531F3...62E418`。

## 2026-07-28 · 远程原版 Skill 确认回填

- 用户明确回复“继续，自动确认回填”，因此在同一隔离工作区调用远程原版
  `apply_all.py --confirmed --in-place --flow-in-place`，未使用 `--force`。
- 写入顺序和结果：先向盈亏核算表明细回填 13 笔，脚本写后逐格回读全部一致；
  随后向到账流转表安全写入 6 笔。跑批台账已把核销日期 2026-07-27 标记为
  “已写表·收工”。
- 两张表的写前备份已保存到隔离工作区的
  `02_我的表副本\备份`，备份 SHA-256 与写入前哈希完全一致；两份变更清单已生成
  到 `04_产出`。
- 五个智云只读取数文件与原运行目录逐一比对，SHA-256 全部保持不变；没有写智云。
- 远程原版存在一个写后总指纹校验时序问题：盈亏写完后会刷新源文件清单，但流转
  写完后不刷新，因此最终 `verify_sources.py verify` 会把已授权的流转写入报告为
  “到账流转表.xlsx 被改动”。这不代表回填失败；盈亏逐格回读、流转写入结果、
  备份和变更清单均已成功生成。本次保持远程 Skill 原样，未修改其代码。

## 2026-07-28 · 回填文件打开问题排查

- 两份回填工作簿均存在，XLSX ZIP 容器可完整解压并包含 `xl/workbook.xml`；
  到账流转表还通过 artifact-tool 导入并识别到 `Sheet1!A1:N110`。
- 盈亏核算表因体积和结构复杂，artifact-tool 导入超过 120 秒，但完整 ZIP 条目读取
  未报错；结合回填时 openpyxl 保存和逐格回读成功，没有发现文件损坏证据。
- 之前消息使用反斜杠的深层 `.codex` 路径，Codex 本地链接可能无法正确打开；
  另有一个 Excel 进程正在运行。已把两份文件复制到下载目录并校验 SHA-256 与回填
  结果一致：
  `核销回填_盈亏核算表_20260727_20260728_153237.xlsx`、
  `核销回填_到账流转表_20260727_20260728_153237.xlsx`。

## 2026-07-28 · 移除内网提示卡与 Skill 安全重置

- 已从全局侧栏移除“部门内网运行 / 文件不会进入 GitHub”组件及全部关联样式；
  生产构建产物中不再包含这两段文案。
- `ar-hexiao-daily` 升级到 1.2.0；对话任务页新增“重置任务”文字按钮和二次确认
  弹窗。重置会清空核销日期、文件绑定、输出列表、执行上下文、进度和错误状态，
  恢复到“等待核销日期”。
- 重置保留对话、动作和运行审计，不撤销已完成写入，不删除备份、上传文件或智云
  加密凭据；存在 queued/running 动作或处于 preparing/applying 时返回 409。
- 新增 `POST /api/workflows/{workflow_id}/reset`；前端同步处理加载、错误、Escape
  关闭、禁用状态和移动端布局。Skill 的触发说明和安全边界已经同步更新。
- 后端完整测试 12 项通过；本次修改文件的 Ruff 检查、Skill UTF-8 quick_validate、
  前端 typecheck/build 全部通过。全仓库 Ruff 仍有供应商同步脚本的既有规范问题，
  本次未批量改动这些上游文件。
- 本地服务已重启，OpenAPI 已包含 reset 路由，API 返回 Skill 版本 1.2.0 且状态为
  published。
- 使用本机 Edge 无头渲染验证 1440×1000 和 375×812：旧提示卡已消失，重置按钮、
  遮罩、说明文字与确认/取消操作在桌面和窄屏均完整可见；验证只打开弹窗，未确认
  重置任何真实任务。

## 2026-07-28 · 角色切换与运行记录空状态优化

- 顶栏角色切换由透明原生 `select` 改为自定义可访问菜单，避免浏览器原生选项列表
  破坏界面风格；新增当前身份说明、权限摘要、选中标记、点击外部关闭和 Escape
  关闭，并保留 `aria-haspopup`、`menuitemradio` 等辅助技术语义。
- 该角色切换当前仍用于内网演示和权限验收，因此保留；接入公司统一登录并由服务端
  下发真实角色后，应移除普通用户主动切换身份的入口。
- 运行记录页将“对话式工作流”和“标准任务”明确分区。标准任务表只在存在对应数据
  时渲染，解决只有表头而没有记录的问题；当全部类型都没有记录时展示带下一步操作
  的统一空状态，筛选无结果时可一键返回全部记录。
- 增加首次加载状态和接口错误提示，避免请求完成前短暂显示“没有记录”；后续轮询
  失败时保留已经取得的记录。
- 前端生产构建通过；后端完整测试 12 项通过。使用本机 Edge 无头渲染验证
  1440×1000 与 375×812：角色菜单无原生下拉、移动端页面宽度为 375/375、没有
  横向溢出；角色切换后菜单关闭且管理员导航正确出现；无记录筛选下表格数量为 0，
  不再出现孤立表头。
- 本次仅修改 `Layout.tsx`、`RunList.tsx` 和关联样式，并新增 `.codex` 视觉验证
  脚本/截图；工作树中此前的工作流重置、后端及 Skill 修改继续保留，尚未提交。

## 2026-07-28 · 当前并发能力核查

- 当前平台可以同时创建、保存、查看和对话多个任务；处于等待日期、等待文件或等待
  人工确认状态的任务不会持续占用执行器。
- `scripts/start.ps1` 当前只启动一个逻辑 Worker，负责
  `python,http,workflow` 三个池。`worker.run_once()` 每次先领取一个标准任务并完整
  执行，标准任务为空时才领取一个 Workflow Action，因此两个都进入执行阶段的任务
  会串行处理，后提交的任务保持 queued。
- Windows 进程列表中的两组同命令 Python 进程分别是虚拟环境启动器及其 Anaconda
  子进程，不代表存在两个独立 Worker；`data/runtime.json` 只登记一个 Worker PID。
- `tool.yaml` 的 `runtime.concurrency_limit` 已有 Schema，但当前领取任务逻辑尚未读取
  或强制执行该值。直接手动多启 Worker 虽可能形成并行领取，但 SQLite 写竞争、
  每 Skill 并发限制、文件写入冲突和 Edge/RPA 会话隔离尚未完备，当前不应视为安全
  的正式双任务并行方案。
- 本次为只读核查，没有修改程序代码或运行配置。

## 2026-07-28 · 多任务并行改造建议

- 推荐目标是“不同任务可并行、同一高风险 Skill 按清单限流、同一外部系统账号/RPA
  资源串行”，而不是简单复制现有 Worker。第一期建议 Python 2、HTTP 2、
  Workflow 2、RPA 1 个执行槽；`ar-hexiao-daily` 暂时保持
  `concurrency_limit: 1`。
- 正式并发前应把 SQLite 切换到 PostgreSQL，并引入 Alembic；当前
  `Base.metadata.create_all()` 不能可靠升级已存在数据库结构。
- 标准任务和 Workflow Action 都需增加 worker/lease/attempt 信息；领取任务使用
  PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED`，同一事务内写入 running、
  worker_id 和 lease，避免两个 Worker 重复领取。Worker 需定时续租，增加超时回收
  与有限重试。
- `runtime.concurrency_limit` 需要真正接入调度。领取前按 Skill ID 获取数据库事务锁，
  统计未过期执行租约；达到上限则跳过候选任务。建议再增加 `resource_key`，
  对同一智云账号、同一外部系统或同一正式文件实施独占锁。
- 启动控制器应按池分别启动多个 Worker，记录 `worker_pids[]`，停止时逐个回收；
  不再让一个 Worker 同时轮询 `python,http,workflow`，避免标准任务长期抢占
  Workflow Action。
- 当前标准运行目录按 run ID、工作流动作目录按 workflow ID/action ID 隔离，基础
  文件隔离可复用；Edge 使用独立非持久 Context，但同一财务系统账号仍建议保持
  单并发，下载和正式写入必须继续使用任务独立目录。
- 最低验证范围应包含：双 Worker 不重复领取、不同 Skill 真并行、同 Skill 上限生效、
  Worker 崩溃后租约回收、取消与重试、同账号 RPA 串行、两个输出目录互不污染、
  PostgreSQL 并发集成测试及两项真实无敏感数据的端到端并行任务。
- 本次只形成基于当前代码的改造方案，尚未修改并发实现、数据库或运行配置。

## 2026-07-28 · 多任务共享模型连接核查

- 两个独立任务可以选择同一个 ModelConnection、模型名称和 API Key。模型服务是
  无状态 HTTP API，每个请求独立携带当前任务的系统规则、阶段状态和最近对话，
  不需要为每个任务单独部署一个模型实例。
- 对话式工作流按 workflow ID 分别保存消息，并在每次调用时仅装配该工作流最近
  20 条用户/助手消息；因此两个任务共用模型连接不会自动混合上下文。
- 参数解释和对话 Tool Calling 位于 FastAPI 请求链路，不通过当前单 Worker 队列；
  两个独立 HTTP 请求可以并发调用同一模型。后续真正的 Python/Workflow/RPA 动作
  是否并行，仍取决于执行 Worker 的并发改造。
- 实际并发上限由千问账号/模型的 QPS、并发连接、Token 和账户余额限制决定。平台
  当前没有模型连接级限流、429 指数退避或请求队列；正式多任务并行时应增加每连接
  Semaphore、超时重试、429 Retry-After 处理和用量审计。
- 同一个 workflow 如果被同时发送两条消息，仍可能产生消息顺序和重复动作竞争；
  应增加 workflow 级互斥或乐观版本号。该风险不影响两个不同 workflow 的上下文隔离。
- 本次为只读核查，没有修改模型调用代码或配置。

## 2026-07-28 · 多任务并行执行实现

- 平台已从单 Worker 改为按池启动多个独立 Worker，默认容量为 Python 2、HTTP 2、
  Workflow 2，共 6 个执行槽；RPA 默认继续关闭。`serve_control.py` 现在保存
  `workers[]` 运行清单，启动时逐个检查，停止时按进程树完整回收。
- 标准任务和 Workflow Action 新增 `worker_id`、`attempt_count`、`heartbeat_at`、
  `lease_expires_at`；Run 和 WorkflowSession 同步保存任务快照中的
  `concurrency_limit`。领取任务时写入执行身份、尝试次数和租约。
- 新增数据库调度锁：SQLite 使用 WAL、30 秒 busy timeout 和
  `BEGIN IMMEDIATE`，其他数据库使用 `scheduler_locks` 行锁。任务领取和同 Skill
  活动数检查在同一锁内完成，因此多个 Worker 不会领取同一个任务。
- `runtime.concurrency_limit` 已接入真实调度：同 Skill 达到上限时，Worker 会跳过
  该任务并继续寻找其他 Skill，不会让一个受限 Skill 阻塞整个队列。
- 执行期间由独立心跳线程续租。只读标准任务在 Worker 异常且租约过期后，可在最大
  尝试次数内重新排队；RPA、高风险写入和 Workflow Action 不自动重试，而是标记失败
  并要求人工检查，防止未知状态下重复写入。
- 增加 SQLite 既有库兼容升级，启动时补充并发字段；新建库直接由 SQLAlchemy 模型
  创建。正式多机部署仍建议 PostgreSQL 和 Alembic，本地部门级小规模并行继续支持
  SQLite。
- 新增 6 项并发测试：两个 Worker 真实重叠、同 Skill 限流、双领取者不重复领取、
  只读租约恢复/写任务拒绝自动重试、Workflow 不同 Skill 并行领取，以及分池 Worker
  进程计划。后端完整测试现为 18 项全部通过；本次相关 Ruff 检查和前端生产构建通过。
- 隔离多进程端到端验证使用两个真实 Worker 和两个真实 Python Skill 子进程，二者
  均 succeeded，由不同 worker_id 执行；开始时间相差约 40 毫秒，约 2 秒执行区间
  完整重叠，`overlapped=true`。验证数据位于 `.codex/parallel-runtime-check`，
  没有进入正式任务数据库。
- 本地平台已在无 queued/running 任务时安全重启。当前健康接口报告
  `configured_execution_capacity: 6`，`python-1/2`、`http-1/2`、
  `workflow-1/2` 六个进程均存活，最近错误日志为空。
- README、架构文档、Skill 接入协议和 `.env.example` 已同步并行配置、租约语义、
  自动重试边界和隔离验证命令。工作树中本轮及此前 UI/重置相关修改均尚未提交。

## 2026-07-29 · 平台启动与过期 PID 防护

- 用户要求启动服务。检查发现昨日 `runtime.json` 仍在，但 API 已不可访问，记录的
  两个旧 PID 已被 Windows 复用为 `svchost.exe` 和 `ApplicationFrameHost.exe`。
  经命令行核验确认没有真实 API/Worker 进程后，仅移除了过期运行记录，没有终止
  这两个无关进程。
- 平台已重新启动于 `http://127.0.0.1:8000`。健康接口返回 status=ok、18 个 Skill、
  无 Registry 错误、配置执行容量 6；Python 2、HTTP 2、Workflow 2 六个 Worker
  进程均存活。
- 修复 `serve_control.py` 只按 PID 判断进程归属的风险：启动和停止现在同时检查
  进程命令行中的 `uvicorn app.main:app` 或 `app.worker + worker_id`。PID 已被其他
  程序复用时会自动清理/跳过过期记录，不会调用 taskkill。
- 新增过期 PID/正确 Worker 命令行识别测试；后端完整测试现为 19 项通过，相关
  Ruff 检查通过。重复执行启动命令会正确返回“平台已经运行”，现有服务保持正常。
- 本轮没有执行真实财务任务、RPA 或工作簿写入；工作树修改仍未提交。

## 2026-07-29 · 同一 Wi-Fi 局域网访问

- 用户希望同一 Wi-Fi 下的电脑和手机都能访问财务 Skill 平台。当前 WLAN 名称为
  `BESTEASY`，IPv4 地址为 `192.168.30.89`，网络类别原为 Public。
- `serve_control.py` 和 `scripts/start.ps1` 已将默认 API 监听地址从
  `127.0.0.1` 改为 `0.0.0.0`；本机健康检查和自动打开浏览器仍使用
  `127.0.0.1`。`data/runtime.json` 现在记录实际 host。
- 平台已在无 queued/running 任务时安全重启，当前监听 `0.0.0.0:8000`；
  `http://127.0.0.1:8000/api/health` 与
  `http://192.168.30.89:8000/api/health` 均返回 status=ok，6 个 Worker 存活。
- 新增 `scripts/enable_lan_access.ps1`：普通 PowerShell 运行时自动请求 UAC，
  将指定 WLAN 设置为 Private，并创建或更新仅限 `Private + WLAN +
  LocalSubnet + TCP/8000` 的入站规则。README 和 `.env.example` 已同步。
- 当前 Codex 进程不是管理员；已触发 UAC 请求，但复查时 WLAN 仍为 Public，
  表示管理员确认尚未完成或已取消。用户需重新运行
  `scripts\enable_lan_access.ps1` 并在提示中点击“是”，其他设备才不会被
  Windows 防火墙拦截。
- 后端完整测试 19 项通过，`serve_control.py` 编译通过，PowerShell 辅助脚本语法
  校验通过。当前测试版仍缺少正式登录鉴权，只应在可信部门 Wi-Fi 上开放。
- 用户随后说明电脑主要使用网线。复查发现物理有线接口“以太网”为
  `192.168.20.207/24`，Wi-Fi 访问设备所在 WLAN 为 `192.168.30.89/24`，
  两者分属 `192.168.20.0/24` 和 `192.168.30.0/24`；有线地址健康检查同样
  返回 status=ok。
- `enable_lan_access.ps1` 已改为默认配置“以太网”，并新增
  `AllowedRemoteAddress` 参数。当前推荐规则为仅允许
  `192.168.30.0/24` 从“以太网”接口访问 TCP/8000；`start.ps1` 默认显示有线
  地址 `http://192.168.20.207:8000`。
- 已再次触发正确参数的 UAC 请求，但复查时“以太网”仍是 Public 且规则不存在，
  说明管理员确认仍未完成。即使 Windows 规则创建成功，若网关禁止
  `192.168.30.0/24` 到 `192.168.20.0/24` 的跨子网访问，仍需调整路由器/VLAN
  隔离策略；替代方案是保留电脑 WLAN 连接并使用 `192.168.30.89:8000`。

## 2026-07-31 · 平台启动

- 使用 `scripts/start.ps1` 启动平台；启动器先安全清理过期运行记录，未报告终止
  无关进程。
- API 当前监听 `0.0.0.0:8000`，本机入口为 `http://127.0.0.1:8000`，有线地址为
  `http://192.168.20.207:8000`。
- `/api/health` 在回环地址和有线地址均返回 `status=ok`；Registry 登记 18 个
  Skill、无 Registry 错误，普通可用列表返回 10 个已发布 Skill。
- Python 2、HTTP 2、Workflow 2 共 6 个 Worker 均存活，进程命令行与各自
  `worker_id` 一致。
- 浏览器实际打开首页并确认标题为“财务 Skill 运行平台”、页面显示“服务正常”，
  财务工具、运行记录和模型接入入口均已正常渲染。
- 本次仅启动和核验平台，没有运行任何财务任务、RPA 或工作簿写入。

## 2026-07-31 · 应收核销日清最近更新核查

- 本次只读核查 `ar-hexiao-daily`，没有生成日清、运行智云取数或写入工作簿。
- 当前平台 API 返回版本 `1.3.0`、状态 `published`；平台 `vendor` 载荷与
  `D:\codex\skills\ar-hexiao-daily` 已安装版的 35 个生产文件逐文件 SHA-256
  一致。
- 2026-07-30 更新包含“差异”列、公式缓存、部分回款拆行及手续费完全忽略等规则；
  2026-07-31 更新包含核销记录身份、跨快照去重、可解释系统重复核销折叠、
  不可解释超核销整笔挂账，以及取数版本
  `2026-07-31-writeoff-record-identity-v1`。
- 使用平台虚拟环境对当前已安装版运行完整测试，结果为
  `256 passed, 5 skipped, 3 warnings`，退出码 0；3 条警告均为 Windows/GBK
  子线程解码告警。
- 已执行 `git fetch origin --prune` 核验源仓库；本地 `HEAD` 与
  `origin/main` 均为 `3a642d4`，远程针对该 Skill 的最近提交仍为
  2026-07-25 的 `49f63a6`。因此 7 月 30–31 日更新已在本机安装版和平台版生效，
  但尚未提交、推送到远程 `finance-skills` 仓库。

## 2026-07-31 · 应收核销 Skill 完整覆盖平台版

- 按用户要求，以当前安装版 `D:\codex\skills\ar-hexiao-daily` 为唯一业务内容基线，
  完整覆盖平台 `skills/ar-hexiao-daily` 中的 `SKILL.md`、`README.md`、配置、
  规则文档和核心脚本；没有保留平台旧版业务规则或旧版核心实现。
- 平台注册版本升级为 `1.3.0`。新取数结构版本为
  `2026-07-31-writeoff-record-identity-v1`，已包含按核销记录身份审计、
  条件性系统重复核销纠正及未解决超核销整笔挂起逻辑。
- 平台包仅额外保留运行必需的 `tool.yaml`、工作流入口和安全凭据桥接
  `fetch_secure.py`；旧的金蝶/RPA 遗留脚本和依赖清单已从该 Skill 包移除。
  `scripts/sync_finance_skills.py` 中对应的发布说明和版本也更新为 `1.3.0`，
  防止后续同步重新降级注册信息。
- 安装版与平台包的 35 个上游生产文件逐项 SHA-256 一致，平台包没有额外业务核心文件。
  `quick_validate` 通过；系统重复核销专项测试 22 项通过；完整 Skill 测试
  256 项通过、5 项因本地可选夹具缺失跳过；平台工作流测试 7 项通过。
  Registry 回读确认 `ar-hexiao-daily` 为 `1.3.0 / published / workflow`，无注册错误。
- 本轮没有运行真实核销日清、没有执行 apply、没有修改智云或财务工作簿，
  也没有提交或推送 Git；项目中原有和无关工作树改动均保留。

## 2026-07-31 · 应收核销写后订单差异表上线

- 平台内置 `ar-hexiao-daily` 升级为 `1.4.0`。确认写入完成后，自动回读上传盈亏表
  的工作副本并生成 `订单写入差异_<核销日>.xlsx`，包含“汇总”“订单对比”
  和“字段差异”三个工作表。
- 核对范围严格限定为本批实际写入订单及拆分新增行，不扫描整张历史订单表作为差异；
  写入不一致时记录计划值和实际值。
- 平台完成提示、工作流测试和 Skill 同步目录已更新；`sync_finance_skills.py`
  的目录说明与版本也同步为 `1.4.0`，避免后续重新同步时降级。
- 验证：平台后端 19 项测试通过；内置脚本编译和 `quick_validate.py` 通过；
  API 回读为 `1.4.0 / published`，健康状态 `ok`，配置执行容量 6。
- 平台已安全重启并加载新版本；重启前排队或执行中的工作流为 0。
- 本轮没有运行真实核销、智云取数或财务工作簿写入。

## 2026-07-31 · 同一 Wi-Fi 设备访问已启用

- 用户要求所有连接同一 Wi-Fi 的设备可访问平台。当前无线网络为 `BESTEASY`，
  本机 WLAN IPv4 为 `192.168.30.89/24`。
- 平台已监听 `0.0.0.0:8000`；将 WLAN 网络类别从 Public 改为 Private，并更新
  Windows 防火墙规则 `Finance Skills LAN 8000`：仅限 Private 配置、
  WLAN 接口、LocalSubnet 来源和 TCP/8000。
- `scripts/start.ps1` 与 `scripts/enable_lan_access.ps1` 的默认接口改为 WLAN；
  README 的局域网说明同步为直接运行 `enable_lan_access.ps1`。
- 本机通过 `http://192.168.30.89:8000` 实际访问首页返回 HTTP 200，标题匹配；
  `/api/health` 返回 `status=ok`。PowerShell 脚本语法检查通过。
- 同一 Wi-Fi 设备当前使用 `http://192.168.30.89:8000` 访问。该内部测试版尚未
  接入正式登录鉴权，因此只应在可信 Wi-Fi 上开放；若 DHCP 地址变化，应以启动输出
  的新 WLAN 地址为准。

## 2026-07-31 · 公网服务器部署可行性初查

- 用户提供公网服务器 `192.144.173.109` 并询问能否部署。本轮仅做只读探测，
  没有登录后安装软件、上传项目或修改服务器。
- TCP 22、80、443 均可达；SSH 服务为 OpenSSH 7.4，允许密码认证，但现有本机
  SSH 密钥未获授权。为避免把明文口令写入命令或日志，本轮没有使用密码自动登录。
- 服务器已有 Nginx 1.27.5；公网 HTTP 会跳转到 `https://eren.xin/`，HTTPS 当前
  承载已有个人博客。部署不能覆盖现有站点，推荐新增独立子域名和 Nginx server block，
  后端只监听 `127.0.0.1`。
- 本地平台核心代码可跨平台运行，要求 Python 3.11+；前端可在本地构建后只上传
  `dist`，服务器无需常驻 Node。Windows PowerShell 启停脚本需替换为 Linux systemd
  服务；Windows/RPA 类 Skill 不能默认视为可在 Linux 正常运行。
- 主要上线阻断项：当前 `auth.py` 使用可由客户端提供的演示身份头，前端也允许切换
  普通/管理员角色，不是真实认证；财务文件平台不能直接公网裸露。至少需要 HTTPS +
  独立子域名 + Nginx/统一身份认证，之后再开放。
- 当前 `data` 目录约 185 MB、包含运行数据库和文件，正式打包时必须排除；服务器应
  初始化空数据目录，并单独配置和备份凭据、数据库和上传文件。
- 后续仍需通过安全 SSH 密钥登录确认服务器发行版、CPU/内存/磁盘、Python 版本、
  systemd、防火墙和证书环境，再决定原生部署或容器部署。

## 2026-07-31 · 公网部署实施进行中

- 用户确认继续部署。公网 22/80/443 可达，服务器现有 Nginx 1.27.5 和
  `eren.xin` 博客保持不动；计划使用独立 `finance.eren.xin`、HTTPS、Nginx
  Basic Auth 和回环地址后端。
- 用户提供的密码认证未通过，未继续猜测口令，也没有修改服务器。已生成专用 ED25519
  部署密钥，指纹为
  `SHA256:HxNttnraNoubtsAjgxtzVjAgj1QA5qnJvjLKB1ngWFM`；私钥只保存在本机
  `.codex/deploy`，没有进入部署包或 Git。
- 新增 `deploy/`：Linux 安装脚本、生产环境模板、API/Worker systemd 单元、
  Nginx ACME 引导配置、HTTPS + Basic Auth 反代配置和部署说明。后端固定监听
  `127.0.0.1:18000`，六个 Worker 由 systemd 独立托管。
- 智云安全登录桥已改为 Windows 使用 Edge、Linux 使用 Playwright Chromium；
  模板与平台内置副本 SHA-256 一致。
- 前端生产构建通过；后端 19 项测试通过；Shell 脚本经 Git Bash `bash -n`
  校验通过；部署桥编译通过。
- 生产包：
  `.codex/deploy/financial-platform-20260731.tar.gz`，795,163 字节，
  SHA-256 `73D03D7F1A2CCC2D7C0218C35AD47DC09363BAF2CF4F2F60A98FBF726D8BBA7F`。
  包含 273 个条目，明确不含 `.env`、`data/`、`.git/`、`.venv/`；敏感模式扫描
  0 命中。
- 已从压缩包独立解压启动验证：`/api/health` 为 `ok`、18 个 Skill、0 个 Registry
  错误，首页 HTTP 200 且标题匹配。测试实例和临时数据已删除，生产压缩包保留。
- 待完成：获得有效 SSH 密钥登录、确认服务器系统与资源、设置
  `finance.eren.xin` DNS、上传安装、签发证书、创建独立登录口令并做公网 401/200
  验收。

## 2026-07-31 · 公网服务器容器部署完成，等待 DNS

- 专用 ED25519 部署密钥已经服务器授权并通过新连接复验；服务器端
  `/root/.ssh/authorized_keys` 已恢复只读保护。后续部署不再使用或记录 root
  明文口令。
- 服务器为 CentOS 7，现有 `eren.xin` 个人博客继续由
  `/srv/personal-blog` 的 Docker Nginx 承载 80/443；财务平台独立部署到
  `/srv/financial-platform`，没有覆盖博客数据、证书或后端。
- 财务平台使用镜像 `financial-platform:20260731`，API 和 Python 2、HTTP 2、
  Workflow 2 共 6 个 Worker 均为 `unless-stopped`、只读根文件系统和无额外
  Linux capabilities。API 不映射宿主机端口，只通过共享 Docker 网络供 Nginx
  访问。
- 服务器内部验收通过：`/api/health` 返回 `production / status=ok`、18 个 Skill、
  0 个 Registry 错误、执行容量 6；`ar-hexiao-daily` 回读为
  `1.4.1 / published`；前端标题正常，Workflow 容器内 Playwright Chromium
  可成功启动。
- 已生成独立 Basic Auth 用户 `finance`，htpasswd 仅以 600 权限保存在服务器；
  本机随机口令只以当前 Windows 用户可解密的 DPAPI 文件保存，未写入项目、部署包
  或上下文文档。
- 已接入每日 02:30 备份，保留 14 天；首次备份
  `/srv/financial-platform/backups/financial-platform-20260731-174739.tar.gz`
  已包含数据库、上传目录、工作流目录和运行目录。部署使用全新数据目录，没有上传
  本机历史财务数据库或文件。
- 博客 Nginx 已安全增加 `finance.eren.xin` 的 HTTP/ACME 引导块和 Basic Auth
  只读挂载；配置启用前经过隔离 `nginx -t`，博客公网 HTTPS 仍返回 200。
- 最终本地部署包为
  `.codex/deploy/financial-platform-20260731.tar.gz`，328 个条目、
  1,146,222 字节，SHA-256
  `C4CA7992AFDFD6C30EE92DA05E65DB45DC566F607CCB20E2733E796D397B1ACB`；
  不含 `.env`、`data`、`.git`、`.venv`、SSH 私钥或 DPAPI 文件。
- 当前唯一外部阻断项是 DNS：Google 与 Cloudflare DNS-over-HTTPS 均返回
  `finance.eren.xin` 为 NXDOMAIN。需在阿里云/HiChina 云解析中新增 A 记录
  `finance -> 192.144.173.109`；解析生效后再签发独立证书、启用 HTTPS 反代并完成
  未认证 401、认证后 200、TLS 和博客回归验收。

## 2026-08-02 · DNS 已生效，SSH 端口暂不可达

- `finance.eren.xin` 已由 Google 与 Cloudflare DNS-over-HTTPS 同时解析到
  `192.144.173.109`，DNS 阻断项已解除。
- 服务器 80/443 仍可达，原有 `eren.xin` 博客返回正常；`finance.eren.xin` 的
  HTTP 引导块仍返回 404，HTTPS 尚未切换到财务平台。
- 本机随后重试 SSH，22、2222、2022、10022、22022 均不可达；因此尚未在服务器
  上执行证书签发或 Nginx 配置切换。需要先通过云厂商控制台确认 `sshd` 监听状态和
  安全组/防火墙是否放行 TCP/22，再继续部署。
- 2026-08-02 继续复查时，22 端口仍超时，而 80/443 可达；财务域名 HTTPS 尚未
  切换，当前 443 仍由原博客默认站点响应。重复 SSH 重试未改变状态。

## 2026-08-02 · 公网 HTTPS 与登录验收完成

- 由于外部 SSH 路径仍超时，改用用户已登录的腾讯云 OrcaTerm 云终端完成服务器
  操作；没有索取或记录新的明文服务器口令。腾讯云轻量服务器防火墙页面已有 TCP
  22 允许规则；服务器内部 `sshd` 正常监听。
- 已为 `finance.eren.xin` 签发 Let's Encrypt 证书，证书 SAN 为该域名，有效期为
  2026-08-02 至 2026-10-31。证书续期演练对 `eren.xin` 和 `finance.eren.xin`
  均显示 success；现有每日 03:17 certbot 任务会续期后 reload Nginx。
- 已备份并替换博客 Nginx 配置中的财务域名块，备份文件为
  `/srv/personal-blog/deploy/nginx/default.conf.before-financial-20260802-124625`。
  配置测试通过后仅重建 Nginx 容器；原博客 HTTPS 回归仍为 200。
- `finance.eren.xin` 公网验收：HTTP 301 到 HTTPS；未认证 HTTPS 401；Basic Auth
  认证后首页 200，标题为“财务 Skill 运行平台”；`/api/health` 返回
  `status=ok`、`environment=production`、18 个 Skill、0 个 Registry 错误、6 个
  执行容量；`ar-hexiao-daily` 返回 `1.4.1 / published`。
- TLS 客户端校验确认主题名和 SAN 均为 `finance.eren.xin`，签发者为 Let's Encrypt
  YR2。HTTP/HTTPS 以及现有 `eren.xin` 博客回归均已验证。
- 修正 Basic Auth 哈希文件权限为 `root:101`、`640`，仅允许 Nginx 容器内的
  `nginx` 用户组读取；文件未公开，明文密码仍只保存在本机 DPAPI 文件。
- 财务平台 API 与 Python 2、HTTP 2、Workflow 2 共 6 个 Worker 全部 running；
  最近日志未发现 error、exception、traceback 或 failed。备份目录已有
  `20260731-174739`、`20260801-023001`、`20260802-023001` 三份备份，并由每日
  02:30 cron 继续生成、保留 14 天。

## 2026-08-02 · 参考图驱动的前端组件标准化

- 按用户提供的“前端全局通用组件标准化文档”要求，统一按钮、输入框、筛选标签、
  卡片、弹出层和表格容器的圆角、尺寸、焦点反馈、层级与过渡。
- 默认控件触控热区不小于 44px，输入控件为 48px；主体禁止横向溢出，长文本允许
  断行；模态遮罩统一为黑色 60%，并建立侧栏、顶栏、弹出层、模态框 z-index token。
- Skill 分类和运行记录筛选补充 `tablist/tab/aria-selected` 语义，移动端保留抽屉导航
  和可操作热区。
- 验证：前端 `npm run typecheck`、`npm run build` 通过；Chrome 1536px 桌面截图、
  375×812 移动 viewport 均通过，无横向滚动；浏览器 error 日志为空。详细记录见
  `design-qa.md`。

## 2026-08-02 · Editorial Operations Console 前端方向

- 用户从三张视觉方案中选定第 1 个：深石墨底、荧光蓝/酸橙强调的财务运营控制台。
- 工作概览已改为“运行指标 + 任务队列 + 近期活动 + 右侧开始任务”三栏结构；保留原有
  路由和 Skill 入口，并补充状态/Skill/关键词筛选、需求输入、文件选择、角色菜单等交互。
- 空运行记录时使用明确标注的预览队列，连接真实任务后自动切换到 API 数据，避免把示例
  数据伪装成真实财务记录。
- 相关实现：`frontend/src/components/Layout.tsx`、`frontend/src/pages/Dashboard.tsx`、
  `frontend/src/styles.css`；桌面和移动截图、验收证据见 `design-qa.md`。
- 验证：前端 `npm run typecheck`、`npm run build` 通过；1536px 桌面与 375px 移动
  viewport 均无页面级横向溢出，浏览器错误为 0。

## 2026-08-02 · 次级页面视觉统一

- 按已选 Editorial Operations Console 方向，将 `财务工具`、`运行记录`、`模型接入`
  三个页面统一为深色控制台语言；业务路由、筛选、连接和删除操作保持不变。
- 移动端筛选标签采用容器内横向滚动并隐藏滚动条，三个页面均保持页面级无横向溢出。
- 相关实现集中在 `frontend/src/styles.css`，验收截图与结果见 `design-qa.md`。

## 2026-08-02 · 工作概览真实空态与快捷入口

- 删除 Dashboard 内置的演示任务/活动数据；`/api/runs` 为空时只展示真实空态，不再显示
  不存在的订单、活动或任务。
- 任务队列横向滚动条改为深色窄样式；侧栏“快捷入口”改为动态读取已发布 Skill，链接
  直接指向对应 Skill 运行页，避免写死不存在的功能名。
- 验证截图：`.codex/dashboard-clean-final.png`；前端类型检查和生产构建通过。

## 2026-08-02 · 深色执行页同步服务器

- 本次前端深色控制台改动已生成部署包
  `.codex/deploy/financial-platform-20260802-clean.tar.gz`，包体 811,991 字节，
  SHA-256 为 `5FF4B1262510A82E4AF7174022531948BCA5969AD188A124C2C81893F8185CB6`；
  排除了 `.env`、`data/`、`.venv/`、`.git/`、`.codex/`、依赖缓存和测试目录。
- 服务器 `/srv/financial-platform` 已更新应用代码、Skill、脚本和 `frontend/dist`；
  服务器 `.env`、SQLite 数据库、上传文件与备份目录均保留。更新前代码备份为
  `/srv/financial-platform/backups/code-before-20260802-144044.tar.gz`。
- Docker Compose 已重新构建并启动 API 与 Python/HTTP/Workflow 共 6 个 Worker；
  内部 `/api/health` 返回 `production / ok`、18 个 Skill、0 个 Registry 错误、6 个
  执行容量。重建后 Nginx 曾缓存旧 API 容器地址，已通过配置测试并 reload 修复。
- 公网验收：未认证 HTTPS 返回 401；Basic Auth 后首页 200、`/api/health` 200，
  页面标题为“财务 Skill 运行平台”，最新深色 CSS 与滚动条样式已从公网返回。

## 2026-08-03 · 服务器核销取数登录超时诊断

- 公网 Workflow 任务 `249fbe9f-3ddf-4b14-9e75-f6d787428d39` 在生成
  2026-07-30 日清时，两次均停在 `fetch_secure.py` 的智云浏览器登录阶段；任务状态为
  `failed`，没有进入判定、日清生成或任何写表动作。智云凭据已配置且两份财务工作簿均已绑定。
- `ar-hexiao-daily` 当前智云入口为代码常量 `http://192.168.10.167:18880`；公网服务器
  `192.144.173.109` 的 Docker Worker 若未接入办公网路由/VPN，无法访问该内网地址，
  浏览器会以 `TimeoutError` 失败。不能通过重试或更换账号解决，也不应把智云直接暴露到公网。
- 后续需先提供服务器到 `192.168.10.0/24` 的受控 VPN/专线/安全中继，并仅放行服务器到
  `192.168.10.167:18880`；连通性通过后再重出日清。当前不允许绕过人在环确认或写表闸。

## 2026-08-02 · Skill 运行页视觉统一

- 将普通 Skill 执行页的上传文件、模型服务、补充说明、参数确认和运行前复核全部切换为深色控制台样式，补齐此前残留的白色表面。
- 对话式 Workflow 的开始卡、聊天面板、侧栏文件和产物卡片同步使用同一套深色 token；移动端菜单按钮与页面滚动条也已统一。
- 验证截图：`.codex/skillrun-console-final.png`、`.codex/skillrun-console-mobile.png`；`npm run typecheck`、
  `npm run build` 通过，浏览器错误为 0，375px viewport 无页面级横向溢出。

## 2026-08-03 · 核销 Skill 最新状态只读核验

- 用户询问 `D:\BESTEASY\financial_pj` 项目中的核销 Skill 是否为最新版；本轮只读核验，未同步、
  未重启平台、未提交或推送代码。
- 项目磁盘中的 `skills/ar-hexiao-daily/tool.yaml` 为 `1.5.0 / published`，同步时间为 15:38；
  项目 vendor 的 34 个上游生产文件与当前本地财务 Skill 源码内容一致，文本差异仅为同步脚本按约定
  清除行尾空格；`fetch_secure.py` 为平台规定的安全登录桥覆盖。关键判定与写入脚本 SHA-256 与当前
  安装版一致。因此，项目目录中的文件是当前本机最新工作区版本。
- 当前本机运行中的平台 API 仍回读 `ar-hexiao-daily 1.4.1 / published`、
  `requires_confirmation=true`；尚未加载磁盘上的 1.5.0。要让运行实例使用 1.5.0，仍需在确认没有
  其它任务执行后安全重启并复核 API。
- Gitee `finance-skills` 的远端 `main` 最新提交为 `4a99919`，仍是需要日清后人工确认的版本；
  本地 1.5.0 的“日清与写前校验通过后直接写工作副本”改动仍在未提交工作树中，尚未进入 Gitee。
  因此 1.5.0 不能称为已发布到远端的正式最新版。
- `financial_pj` 自身 GitHub origin 本轮 fetch 返回 repository not found；本地缓存的 `origin/main`
  与 HEAD 同为 `b2b2687`，但无法据此确认远端当前状态。项目工作树原有大量未提交改动均保持不变。

## 2026-08-03 · 本机平台加载核销 Skill 1.5.0

- 用户要求更新平台 Skill；范围限定为本机 `D:\BESTEASY\financial_pj` 运行实例，未更新公网服务器，
  未提交或推送 Gitee。
- 重启前 `/api/runs` 为 0 个任务，排队/运行任务均为 0；运行台账中的 API 与六个 Worker PID
  均经命令行和 worker_id 核对无误。后端测试 19 项通过。
- 使用项目进程管理脚本安全停止旧 API 和六个 Worker，再以 `0.0.0.0:8000`、不自动打开浏览器的方式
  重新启动。新运行台账记录 API 1 个、Python/HTTP/Workflow 各 2 个 Worker，共 6 个执行 Worker。
- 重启后 `/api/health` 返回 `development / ok`、18 个 Skill、0 个 Registry 错误、执行容量 6；
  `ar-hexiao-daily` 回读为 `1.5.0 / published`、`requires_confirmation=false`，Skill hash 为
  `574abea9246100cbf0891bb3b215c9fe867a2446307047b594de2abdff6df9fd`。
- 首页 HTTP 200 且标题匹配；平台内置核销脚本全量编译通过。更新完成后任务总数与活动任务数仍为 0。
  局域网访问地址仍为 `http://192.168.30.89:8000`。

## 2026-08-03 · 核销 Skill 前置资料启动流

- 应收核销日清入口移除聊天框，改为上传前置文件、选择核销日期、选择模型服务后开始核销；开始前逐项校验文件数量、日期、模型和智云凭据。
- 新增直接启动 Workflow 的后端入口，并保留人工确认写入闸门；执行页改为阶段时间线、审计记录、产物、失败重试和确认写入，不再依赖聊天输入。
- 本机 UI 验收截图为 `.codex/workflow-launch-final.png`，`scrollWidth=clientWidth=1270`；`npm run typecheck`、`npm run build`、后端 19 项测试均通过。
- 出于财务数据安全，原始工作簿仍由隔离 Worker 读取和计算，模型负责流程理解与控制，不把整张原始财务表直接发送给模型。

## 2026-08-03 · 工作台动态数据与双主题

- Dashboard 现在合并 `/api/runs` 与 `/api/workflows`，按真实创建/完成/异常状态计算今日任务、成功率、平均处理时长、待处理和异常任务，并定时刷新。
- 快捷入口按当前用户可见 Skill 的实际运行次数排序；侧栏“系统状态”卡片删除，顶栏“平台正常/平台异常”来自 `/api/health`。
- Dashboard 开始任务会把上传文件先保存为真实 FileRecord，再将文件记录和描述通过路由状态带入对应 SkillRun；没有实际点击运行时不会创建 Run/Workflow。
- 新增可访问的 SelectMenu、日期选择按钮、全局搜索结果面板和白天/夜间主题切换；菜单、角色选择、模型选择和滚动条不再使用白色原生视觉。
- 本机服务已重启并验证：API `development / ok`，前端 typecheck/build 通过，后端测试 19 项通过，桌面页面无横向溢出、浏览器错误为 0。

## 2026-08-03 · 任务历史清理、路径管理员入口与主题收口

- 清理前已停止本机 API 和 6 个 Worker，并将 `data/financial.db`、SQLite sidecar 和
  `data/workflows` 完整备份到 `.codex/backups/history-before-clean-20260803-165758/`。
- 清理了 25 条旧 `WorkflowSession`、196 条消息、27 条动作和 96 条工作流输出文件记录；
  `runs`、`run_events`、`run_model_audits` 同步核对为 0。原始输入上传记录保留为 29 条，
  避免误删用户材料；历史工作流目录移入同一备份目录，可恢复。
- 工作流列表只显示带 `started_from_form` 标记的直接启动任务；旧的兼容聊天创建接口仍保留给
  API 测试，但不会再把“尚未点击开始核销”的会话显示到工作台。直接开始后才会创建并排队任务。
- 普通端不再显示角色切换器；`api.ts` 按当前 URL 派生身份，只有手动访问 `/admin` 才发送
  `skill_admin` 请求头并显示管理员导航，普通路径固定为财务员工端。运行记录列表、标准任务详情、
  工作流执行页均显示完整任务 ID。
- 浅色主题补齐工作流 Hero、前置上传、日期、模型选择、执行进度、审计日志和文件卡片的文字/背景
  对比度；修复隐藏日期输入被通用 `.field input` 撑宽造成的页面横向滚动。深浅主题均通过桌面点验。
- 验证：`npm run typecheck`、`npm run build`、`.venv\\Scripts\\python.exe -m pytest backend -q`
  均通过；本机 `/api/health` 为 `ok`、18 个 Skill，核销 Skill 为 `1.5.0 / published`；
  浏览器核验首页真实空态、运行记录空态、全局搜索、模型/日期菜单、主题切换、普通端与 `/admin` 路径，
  `scrollWidth=clientWidth=1270`，未发现角色切换器或浏览器布局错误。

## 2026-08-03 · 全页面双主题统一回归

- 复查发现旧控制台规则仍覆盖了 `SkillList`、`RunList`、`ModelSettings` 和 `Admin` 的浅色样式，
  表现为深色空态、Skill 卡、模型连接面板和管理员表格混入浅色页面。
- 已在主题覆盖层补齐所有次级页面：筛选条、搜索框、Skill 卡片、风险标签、运行记录空态/表格、
  工作流记录卡、模型接入面板/连接卡、管理员表格、标准任务详情、产物和侧栏卡片；深色默认样式保持不变。
- 本机浏览器逐页检查 `/`、`/skills`、`/runs`、`/models`、`/admin`、`/skills/ar-hexiao-daily`，
  浅色和深色均无白色/深色主题串色，页面级 `scrollWidth=clientWidth`；并点击验证了 Skill 分类、
  运行状态筛选、模型下拉、管理员重新扫描按钮。
- 前端 `npm run typecheck`、`npm run build` 通过；本机服务已重启加载最新 `frontend/dist`。

## 2026-08-03 · 项目明细补录 Skill 接入平台

- 本地平台新增 `skills/project-detail-to-ledger`，平台登记脚本 `scripts/sync_finance_skills.py` 增加可执行 Skill 元数据；上传项目明细表和盈亏核算表后，桥接器生成结果工作簿与 `_补录报告.json`。
- 平台入口真实测试通过：937 行追加、数字字段转换、单号留空、ZIP/XML 可读和原件不改均通过；平台本地提交为 `f72c9f4`，只包含本 Skill 和对应登记代码，既有工作树改动未纳入提交。
- 平台仓 GitHub origin 当前为 `https://github.com/abbbzaq/financial_pj.git`，GitHub API 返回 Repository not found，因此本轮未推送平台提交；待确认正确远端仓库地址后再发布。
- 本机运行实例无需重启即回读新 Skill：`/api/health` 为 `ok`、Skill 数量 19，`project-detail-to-ledger` 为 `1.0.0 / published`，两个上传角色和结果/报告输出均已加载。

## 2026-08-03 · 标准 Skill 执行页浅色主题补齐

- 用户反馈普通 Skill 页面仍残留深色上传卡、说明输入框、模型选择器和右侧执行摘要；原因是后置控制台规则覆盖了旧浅色样式。
- 在 `frontend/src/theme-overrides.css` 最后增加标准运行页专用浅色覆盖，统一 `.upload-card`、`.field`、`.task-model-selector`、`.summary-sticky`、参数按钮和校验提示的背景、边框与文字对比度，深色主题保持原控制台样式。
- 本机重启后逐页检查 10 个已发布 Skill（含应收核销日清 Workflow）：浅色页面主要表面均为白色/浅蓝，上传卡和输入控件为浅色；深色页面恢复深色表面；所有页面 `scrollWidth=clientWidth=1270`。
- 验证：前端 `npm run typecheck`、`npm run build` 通过；标准 Skill 页面截图和明暗主题计算样式检查通过。

## 2026-08-04 · Gitee Skill 定时同步方案

- 新增 `scripts/sync_from_gitee.ps1`：从公开 Gitee `Lee157/finance-skills` 的 `main` 分支独立检出，
  检查必需 Skill、记录提交 SHA；检测到新提交时先备份平台 `skills`，调用现有同步脚本，失败自动恢复，
  平台原本运行时才停止/重启并执行 `/api/health` 检查。不会修改 `data` 业务数据库或上传文件。
- README 增加 Windows 任务计划程序示例。尚未注册系统任务，也未执行远程同步；需先手动运行一次并确认
  版本差异，再按需注册每小时任务。私有仓库凭据不得写入脚本。

## 2026-08-04 · 本机 Gitee 定时任务已启用

- 隔离校验通过：Gitee `main` 当前为 `22cf7f30`；平台目录未被修改。远端缺少两个目录级 Skill
  (`jdy-cashflow-export`、`jdy-cashflow-reconcile`)，同步逻辑会保留本地版本；可执行 Skill 缺失则中止。
- 由于本地应收核销 Skill `1.5.0` 与 Gitee 内容存在未发布差异，已将 `22cf7f30` 记录为当前基线，
  防止任务首次运行回退本地版本。之后检测到新的 Gitee 提交时才会进入暂存、备份、替换和重启流程。
- 已注册当前用户 Windows 任务 `Finance Skill Gitee Sync`，每小时执行一次，任务状态 `Ready`；
  任务已设置为错过计划后尽快补跑、禁止并发实例。手动执行和任务计划程序实际触发均返回成功（`LastTaskResult=0`），
  结果为跳过当前基线提交。本机平台健康状态保持 `ok`。

## 2026-08-04 · 本地核销更新已推送 Gitee

- 已将本地应收核销日清直接写入流程和配套测试同步到 Gitee `main`，提交为 `4bf2dc6`；
  Gitee 主线现已包含本地更新。Gitee 基线已更新到 `4bf2dc62`，定时任务不会重复重启本机平台。
- 推送使用 `id_ed25519_gitee` 的 SSH 非交互模式；仓库级 `core.sshCommand` 已设置 `BatchMode=yes`，
  后续推送不会弹登录框。业务数据库、上传文件、浏览器配置和未确认的 RPA Skill 均未推送。

## 2026-08-04 · 修复核销日期点击无响应

- 根因：日期原生输入框被绝对定位到页面可视区域外，并设置 `pointer-events:none`；当前内嵌浏览器不提供
  `showPicker()`，按钮回退点击因此没有可见效果。
- 修复：在日期按钮外增加相对定位控制层，让原生 `input[type=date]` 覆盖整个按钮并接收点击；按钮视觉保持不变，
  键盘/鼠标均可直接触发原生日历，选择日期仍由 React `onChange` 写入表单状态。
- 验证：`npm run typecheck`、`npm run build` 通过；本机服务重启后，日期输入框实际获得焦点且可见点击区域为
  `615.2 × 48px`，`pointer-events:auto`、`z-index:2`；API 健康状态 `ok`。

## 2026-08-04 · 应收核销多日期串行批次

- 应收核销入口支持逐个添加日期或添加连续日期范围，单批最多 7 天；已选日期按升序
  展示，可逐项移除。开始前继续强制核验两份工作簿、日期、模型和智云凭据。
- 后端新增 `WorkflowBatch`、批次启动/查询/续跑接口；一次提交生成一个 `BAT-*`
  批次 ID 和每个日期独立的 Workflow ID。运行记录和工作台将批次作为一条真实任务
  展示，批次详情显示逐日状态、进度和子任务 ID。
- 同一批次只把第一天排队；前一天完成日清、写前校验、工作副本写入和回读后，平台
  将两份结果副本登记为受控文件并传给下一天。后续日期不会并行操作同一份表。
- 日清 Skill `requires_confirmation: false` 时，表单启动任务在日清和写前校验通过后
  自动写隔离副本并生成订单差异表；旧的显式人工确认工作流仍保持兼容。
- 任一天失败会把批次标记为失败并暂停后续日期；只有准备阶段失败允许“从失败日期
  继续”，已经成功的日期不会重跑。写入阶段失败禁止自动重试，需先人工核对副本。
- SQLite 启动迁移会补充批次关联列并创建批次表；旧单日任务保持兼容且不会被误归入
  批次。没有为界面验收创建任何虚假运行记录或真实核销任务。
- 验证：后端 20 项测试通过（新增两日严格串行与副本传递测试）；前端 `typecheck`、
  `build` 通过。浏览器实测单日添加、连续范围添加、日期移除、明暗主题和运行记录空态；
  页面 `scrollWidth=clientWidth`，浏览器错误 0。本机服务已重启，`/api/health=ok`、
  19 个 Skill，批次启动和续跑路由均已加载。

## 2026-08-04 · 192.168.20 网段访问诊断

- 平台电脑同时连接两个局域网：有线网卡为 `192.168.20.207/24`，WLAN 为
  `192.168.30.89/24`；平台监听 `0.0.0.0:8000`，两个本机地址访问健康接口均返回 200。
- `192.168.20.39` 与平台有线网卡属于同一子网，双向链路可达；该设备应访问
  `http://192.168.20.207:8000/`，而不是 WLAN 地址或子网网络地址
  `192.168.20.0`。Windows 有线网卡为 Private，现有 TCP 8000 入站规则允许
  `LocalSubnet`，未发现平台端监听或防火墙阻断。
- 本次仅完成只读网络诊断，没有修改网卡、路由或防火墙设置。

## 2026-08-05 · GitHub 私有仓库发布

- 原 GitHub origin `abbbzaq/financial_pj` 不存在；当前 GitHub 令牌实际账号为 `ErenYeager2002`，已创建私有仓库 `ErenYeager2002/financial_pj` 并将 origin 更新到该地址。
- 本地 `main` 历史已先推送为远端默认分支；当前项目源码、文档、部署脚本和托管 Skill 在现有功能分支提交并通过草稿 PR 发布。
- `.gitignore` 明确排除 `financial.db*`、`.codex/` 和 `.skill-sync/`，运行数据库、本地校验产物、上传文件和凭据不进入 GitHub。

## 2026-08-05 · 独立 Linux 服务部署

- 以 GitHub 发布提交 `f22134d` 的源码和本地构建的前端产物部署到独立
  `/opt/financial-platform`，运行数据使用全新的
  `/var/lib/financial-platform`；未迁移本机数据库、上传文件、凭据或历史财务材料。
- 新增本机回环地址上的 API 服务和 Python/HTTP/Workflow 各 2 个 Worker，健康接口返回
  `production / ok`、19 个 Skill、0 个 Registry 错误和 6 个执行容量；原有看板与 Nginx
  服务保持 active，未修改其配置、端口或数据。
- 目标机只有 Python 3.14，项目依赖声明为 Python 3.11+；依赖已通过镜像安装并完成启动验证。
  Playwright Chromium 下载源未能完成下载，因此网页自动化任务需在补齐 Chromium 后再启用；
  API、文件处理和非浏览器 Worker 已可运行。

## 2026-08-05 · Headless Chromium 下载复核

- 按用户指示尝试 `playwright install --only-shell chromium`，该包约 115 MB，低于完整
  Chromium 的约 184 MB。默认下载源连续观察后仍为 0%；备用镜像连接超过 90 秒仍无日志
  或下载字节，因此已停止两个下载进程，并回滚了新的浏览器目录环境配置。
- 复核 API 和 Python/HTTP/Workflow 共 6 个 Worker 仍为 active，回环健康接口仍返回 `ok`。
  结论是该服务器到浏览器二进制下载源的链路不可用，而非平台服务或 Python 依赖安装问题。

## 2026-08-06 · 本机平台重新启动

- 发现 `data/runtime.json` 留有过期 PID，但本机 8000 端口未监听；使用 `scripts/start.ps1` 清理过期记录并重新启动本机平台。
- 当前 API 监听 `0.0.0.0:8000`，Python、HTTP、Workflow 各 2 个 Worker；首页和 `/api/health` 在回环及当前三块网卡地址上均返回 HTTP 200。
- 健康状态为 `development / ok`，登记 19 个 Skill、0 个 Registry 错误；当前局域网常用地址为 `http://192.168.30.89:8000/`，有线同网段也可使用 `http://192.168.20.207:8000/`。

## 2026-08-06 · 多厂商模型 API Key 接入

- 新增 `backend/app/model_providers.py` 厂商注册表：内置 6 家（qwen、deepseek、zhipu、
  moonshot、openai、doubao）+ 管理员专用 custom_openai，均为 Chat Completions 协议。
  每家定义固定 base_url、发现模式（api/manual/hybrid）、include/exclude 模型模式、
  首选模型和是否允许手动填模型/部署 ID。
- 前端改为“必选供应商 + API Key”手动接入：加载页面时读取 `GET /api/model-providers`；
  密钥只发送给所选供应商；custom_openai 显示 HTTPS 服务地址和模型输入框，manual/hybrid
  允许填写模型名称或部署 ID；删除“自动识别所有供应商”的旧文案。
- 兼容旧客户端：不传 `provider_id` 时仍只按千问探测，不向其他供应商发送密钥；
  旧的 qwen 连接支持列表、刷新、选择和运行。新连接按 owner_id + department_id +
  provider + base_url + API Key 指纹去重；同密钥接不同供应商会生成独立连接。
- 仅对最终选定的默认/手动模型做一次最小 Tool Calling 冒烟验证，不逐模型测试；
  api 模式必须从 `/models` 目录发现，manual 模式不读目录，doubao/custom_openai 为
  hybrid（目录失败时回退手动模型或部署 ID）。模型过滤排除 embedding/image/audio/
  speech/moderation/rerank 等非对话模型，不依赖严格单版本号正则。
- 运行态：`LlmConfig` 新增 `protocol` 与 `extra_body`；`orchestrator.py` 和
  `workflow_orchestrator.py` 移除写死的千问判断，统一合并 `build_extra_body` 结果，
  且 extra_body 不允许覆盖 model/messages/tools/tool_choice。qwen3.x 仅在适用模型注入
  `enable_thinking:false`，kimi-k2.x 注入 `thinking:disabled`，其他厂商不会收到
  千问专有参数。新增可选环境变量 `FINANCIAL_LLM_PROVIDER`，未设置时保持原
  environment 连接行为。
- 安全：内置厂商 base_url 固定不可改；custom_openai 仅管理员可用，base_url 必须
  HTTPS，服务端解析并拒绝回环、链路本地、内网地址（含 DNS rebinding 防护）。
  完整密钥不出现在日志、异常、测试输出、API 响应或本上下文文档；存储仍为 Fernet
  加密，前端只显示脱敏提示。
- 验证：后端 44 项测试全部通过（新增 `tests/test_model_providers.py`，覆盖注册表、
  模型过滤与未来模型、手动选择只命中所选厂商、旧请求仅千问、未知厂商拒绝、错误
  厂商不继续探测、三种发现模式、Tool Calling 验证、qwen 参数隔离、连接隔离、
  旧 qwen 刷新、custom_openai 权限与 SSRF、响应不泄露密钥）；Ruff 0 错误；
  前端 typecheck/build 通过。
- 运行状态：重启前活动任务为 0；已安全重启，`/api/health` 为 `development / ok`、
  19 个 Skill、0 个 Registry 错误、6 个 Worker（python 2/http 2/workflow 2）全部
  存活；首页与健康接口 200；普通用户可见 6 家供应商，管理员可见 7 家。
- 待人工验证：使用真实厂商密钥逐家接入验收；deepseek 旧名模型、kimi-k2.x 思考关闭、
  豆包部署 ID、智谱/OpenAI 实际工具调用行为需在真实厂商环境复核。本任务未使用
  真实 API Key、未创建虚假财务任务、未运行真实写表任务；工作树修改未提交。

## 2026-08-06 · 多厂商模型接入只读验收

- 完整后端测试 `44 passed`，Ruff 通过，前端 `typecheck` 与生产构建通过；运行实例首页和健康接口返回 200，状态为 `development / ok`、19 个 Skill、0 个 Registry 错误、6 个 Worker；普通用户接口返回6家厂商，管理员返回6家加 `custom_openai`。
- 当前不予功能验收通过：Tool Calling 探针只检查 HTTP 成功，不检查响应是否包含目标 `tool_calls`，且使用 `tool_choice=auto`；只读独立探针已证明无任何工具调用的 HTTP 200 响应仍会被接受。连接后切换模型也没有重新验证 Tool Calling。
- `api` 发现模式在发现列表为空但请求携带手工模型时会接受任意模型，绕过了该模式必须通过目录发现的边界；前端同时把 `hybrid` 模式实现为模型必填，使豆包无法从页面执行纯自动发现。
- 自定义地址校验只在保存前解析一次 DNS，实际请求时由 HTTP 客户端再次解析，尚不能称为完整 DNS rebinding 防护。真实六厂商 Key 仍未验证；浏览器视觉验收因当前浏览器控制运行环境无法初始化而未执行，未改业务代码。

## 2026-08-06 · 多厂商模型接入验收问题修复

- 修复四类问题：
  1. Tool Calling 验证改为强制 `tool_choice` 指定 `tool_call_supported` 函数，
     `max_tokens=32`，HTTP 200 后必须解析 `choices/message/tool_calls` 非空、
     函数名精确匹配、`arguments` 为合法 JSON 对象，否则 422「模型 xxx 返回成功，
     但没有完成平台要求的 Tool Calling 验证。」；旧 qwen 连接（不传 provider_id）
     同样执行最终模型验证。
  2. `select_model()` 切换前先解密 Key 并按 `connection.base_url` 重新执行
     Tool Calling 验证；失败返回 422 且 `selected_model`、状态、模型列表全部不变。
  3. `_resolve_models()` 严格三模式：`api` 目录为空或手工模型不在目录一律拒绝、
     不再接受任意手工模型；`manual` 必填且命中排除规则拒绝；`hybrid` 手工模型
     通过排除规则后追加进发现列表（不丢弃既有发现），目录为空且无手工模型时报错。
  4. 自定义地址安全升级：新增环境变量 `FINANCIAL_LLM_CUSTOM_HOST_ALLOWLIST`
     （逗号分隔精确主机名，默认空）。空白名单时 custom_openai 连接直接 422
     「尚未配置允许的自定义模型服务域名。」且不发任何网络请求；必须 HTTPS、
     禁止 userinfo 与 fragment、主机名与白名单精确匹配（无后缀模糊）、DNS 解析
     的全部 IP 必须为公网地址（拒绝私网/回环/链路本地/reserved/组播/未指定），
     规范化端口与路径；`/models`、Tool Calling 验证、refresh、custom_openai
     运行态真实请求统一走 `secure_llm_request`/`chat_completion_request`
     安全入口，自定义请求不跟随重定向；运行态校验失败时参数解释与工作流决策
     安全回退本地规则。
- 前端 `ModelSettings.tsx`：`manual` 必填、`hybrid` 可选（留空自动发现）、
  `api` 不显示模型框、custom_openai 服务地址必填；按钮禁用与 connect() 前置
  检查使用同一套规则；切换供应商清空 baseUrl（离开 custom_openai 时）与
  modelName，保留 API Key。
- 测试 Mock 纠正：`FakeOkResponse` 带真实 `choices/message/tool_calls` 结构与
  可解析 arguments；新增 6 种失败响应（200 普通文本、200 `tool_calls=[]`、
  200 错误函数名、200 非法 arguments、400/401、网络超时）及白名单 10 类、
  切换重验证、严格三模式、运行态安全入口等新测试；修复既有 e2e/工作流测试的
  POST Mock。独立回归探针证明：200 无 tool_calls 被拒绝、api 目录为空拒绝
  手工模型、hybrid 保留发现并追加手工模型、切换失败后数据库 selected_model
  不变。
- 验证：后端完整测试 `67 passed`（上轮 44 项 + 本轮新增 23 项），Ruff 0 错误，
  前端 `typecheck`/生产构建通过，`git diff --check` 无空白错误。
- 运行状态：重启前 runs/workflow_actions/workflow_sessions 均无
  queued/running/preparing/applying 活动任务；已安全重启，
  `/api/health` 为 `development / ok`、19 个 Skill、0 个 Registry 错误、
  6 个 Worker（python 2/http 2/workflow 2）；首页与健康接口 200；
  普通用户 6 家、管理员 6 家加 `custom_openai`。
- 浏览器视觉验收已实际执行（本机 Edge 无头渲染）：供应商下拉 6 家与预期一致、
  豆包留空模型可提交、api 模式不显示模型/地址框、切换供应商保留 Key 并清空
  模型名、桌面深浅主题与 375px 移动端均无横向溢出、控制台 0 错误；截图在
  `.codex/models-verify-check/`。custom_openai 表单为管理员专用，前端仅
  `/admin` 路径发送管理员身份，模型页默认员工端不可见（服务端 API 已验证
  管理员可见 7 家）。
- 待人工验证：真实六厂商 Key 需持有人逐家验证；本任务未使用真实 API Key、
  未创建虚假财务任务、未运行真实写表任务；工作树修改未提交。

## 2026-08-06 · 自定义服务非公网地址判断修复

- `validate_https_base_url()` 的 IP 判断改为以 `is_global` 为主要判据，并保留
  `is_multicast` 明确拒绝：`if not address.is_global or address.is_multicast`。
  修复旧逻辑分别判断 private/loopback/link-local/reserved/multicast/unspecified
  时放过 `100.64.0.0/10` 共享地址空间的问题（如 100.64.0.1 的 is_global=False
  且 is_private=False）；当前 Python 3.13.9 环境下组播地址（224.0.0.1、ff02::1）
  的 is_global 为 True，因此必须保留 is_multicast 判断。DNS 返回的全部地址只要
  有一个不满足条件即拒绝，混合解析不会因存在公网地址而通过。
- 新增边界测试（全部 monkeypatch DNS，不访问真实网络）：拒绝 100.64.0.1、
  100.127.255.254、198.18.0.1、192.0.0.8、2001:db8::1、224.0.0.1、ff02::1；
  通过 1.1.1.1、8.8.8.8、2606:4700:4700::1111；trusted.example 同时解析到
  1.1.1.1 与 100.64.0.1 时混合解析必须拒绝。
- 独立回归探针 `.codex/ip-global-probe.py` 输出：
  `100.64.0.1 -> rejected`、`100.127.255.254 -> rejected`、
  `224.0.0.1 -> rejected`、`1.1.1.1 -> accepted`，`probe_ok=True`。
- 验证：后端完整测试 `70 passed`（新增 3 项边界测试），Ruff 0 错误，
  `git diff --check` 无空白错误；前端未改动。
- 运行状态：重启前 runs/workflow_actions/workflow_sessions 均无活动任务；
  已安全重启，`/api/health` 为 `development / ok`、19 个 Skill、
  0 个 Registry 错误、6 个 Worker（python 2/http 2/workflow 2）；首页与
  健康接口 200；普通用户 6 家、管理员 6 家加 `custom_openai`。
- 真实六厂商 Key 仍待持有人验证；本任务未使用真实 API Key、未运行真实
  厂商请求或财务任务；工作树修改未提交。

## 2026-08-06 · 新增 MiniMax / 海螺 AI 厂商

- `backend/app/model_providers.py` 注册表新增第 7 家内置厂商 `minimax`
  （MiniMax / 海螺 AI）：OpenAI 兼容 `https://api.minimaxi.com/v1`，
  discovery_mode=api；include `^MiniMax-[A-Za-z0-9]+(?:[.-][\w.-]*)?$`
  （覆盖 M3 / M2.7 / M2.7-highspeed / M2.5 / M2.1 / M2 / Text-01 等）；
  排除 vl/vision/image/video/audio/speech/tts/asr/whisper/embedding/
  rerank/moderation/ocr/music 及 `-her` 角色扮演模型；preferred 顺序
  M3 → M2.7 → M2.5 → M2.1 → M2。
- 前端无需改动（`/api/model-providers` 动态渲染）；管理员与普通用户共用。
- 测试更新：注册表断言改为 7 家内置（含 minimax 及 base_url/discovery 断言），
  端点测试普通用户列表加入 minimax，过滤测试新增 MiniMax 用例
  （M2-her / VL-01 / Speech-01 / image-01 / video-01 被正确排除），
  build_extra_body 默认空覆盖加入 minimax；过滤排序遵循 preference 顺序
  （M3、M2.7、M2、M2.1-highspeed、Text-01）。
- 验证：后端完整测试 `70 passed`，Ruff 0 错误，`git diff --check` 干净。
- 运行状态：重启前无活动任务；已安全重启，health `development / ok`、
  19 Skills、0 Registry 错误、6 Worker；普通用户 7 家、管理员 8 家
  （含 custom_openai）。
- MiniMax 真实 Key 待持有人验证；本任务未使用真实 API Key、未运行真实
  厂商请求或财务任务；工作树修改未提交。

## 2026-08-06 · MiniMax Tool Calling 验证修复

- 现象：`MiniMax-M3` 接入时返回 HTTP 200 但无 `tool_calls`，报
  「模型 MiniMax-M3 返回成功，但没有完成平台要求的 Tool Calling 验证」。
- 根因（对照官方 OpenAI 兼容文档）：① MiniMax 端点的 `tool_choice` 仅支持
  `none`/`auto` 字符串，不支持 `{"type":"function","function":{...}}`
  对象强制形式，被忽略后模型按 auto 行为自由回复；② `MiniMax-M3` 思考
  默认开启（thinking omitted → on），`max_tokens=32` 会被思考内容耗尽
  导致截断、无法输出工具调用。
- 修复：
  - `build_extra_body` 新增 `minimax` + `^MiniMax-M3(?:[.-]|$)` 匹配 →
    `{"thinking": {"type": "disabled"}}`（M3 支持禁用思考；M2.x 不支持
    禁用，不传该参数）；验证与运行时请求均生效。
  - `_verify_tool_calling` 对 minimax 专用路径：不发送 object 形式的
    `tool_choice`，改用 system 指令「你必须调用提供的 tool_call_supported
    工具并返回空参数对象。」强制调用，`max_tokens` 提至 1024 容纳 M2.x
    不可禁用的思考输出；其他厂商行为不变（object tool_choice + 32）。
- 新增测试 2 项：M3 验证请求不含 tool_choice、含 system 强制指令、
  max_tokens=1024、thinking=disabled；M2.7 验证请求同样无 tool_choice、
  1024 token、且不携带 thinking 参数；build_extra_body 断言补 M3 /
  M3-priority / M2.7 / M2.1-highspeed 四种模型。
- 验证：后端完整测试 `72 passed`，Ruff 0 错误，`git diff --check` 干净。
- 运行状态：重启前无活动任务；已安全重启，health `development / ok`、
  19 Skills、0 Registry 错误、6 Worker。
- 待持有人用真实 Key 重连 `MiniMax-M3` 确认 Tool Calling 验证通过；
  本任务未使用真实 API Key、未运行真实厂商请求或财务任务；工作树未提交。

## 2026-08-06 · 多厂商模型接入独立复验

- 独立复跑确认后端 `67 passed`、Ruff 通过、前端 `typecheck`/生产构建通过；运行实例仍为 `development / ok`、19 个 Skill、0 个 Registry 错误、6 个 Worker，首页200，普通用户6家、管理员7家。三张现有验收截图已人工查看，桌面深浅主题和375px移动端未见明显溢出或布局异常。
- Tool Calling 响应结构校验、切换模型重验证、严格三种发现模式和 hybrid 前端可选模型均已按前次问题修复。
- 当前仍不予最终验收通过：`validate_https_base_url()` 通过枚举私网/回环等属性判断，但没有要求 `address.is_global`；独立探针证明 `100.64.0.1`（`is_global=False`）会被接受。该共享地址可能在运营商网络、VPN或叠加网络中可达，不符合“全部解析结果必须为公网地址”的安全约束。应改为 `if not address.is_global: reject` 并增加 `100.64.0.1` 等非 global 地址回归测试后再验收。

## 2026-08-06 · 多厂商模型接入最终独立验收

- 已确认地址判断改为逐个执行 `not address.is_global or address.is_multicast`；共享地址、文档地址、组播地址和公网 IPv4/IPv6 回归覆盖完整，混合解析中任一非公网地址会使整体拒绝。独立离线探针结果为3个非公网/组播地址拒绝、`1.1.1.1` 接受、`probe_ok=True`。
- 独立复跑后端 `70 passed`、Ruff 通过、`git diff --check` 无错误；运行实例为 `development / ok`、19 个 Skill、0 个 Registry 错误、6 个 Worker，首页200，普通用户6家、管理员7家。
- 本地代码范围验收通过；剩余事项仅为真实六厂商 Key 由持有人逐家验证。当前全部改动仍未提交，未运行真实厂商请求或财务任务。

## 2026-08-06 · MiniMax 厂商独立验收

- 对照 MiniMax 官方文档确认：国内 OpenAI 兼容地址为
  `https://api.minimaxi.com/v1`，模型发现接口为 `GET /v1/models`；官方模型列表
  包含 `MiniMax-M3`、`MiniMax-M2.7`、`MiniMax-M2.5`，Chat Completions 支持
  `tools`，当前注册表的 base_url、api 发现模式、M3 优先级与文本模型过滤方向一致。
- 独立检查确认普通用户供应商接口返回 7 家（含 `minimax`），管理员返回 8 家
  （含 `custom_openai`）；运行实例 `/api/health` 为 `development / ok`、19 个
  Skill、0 个 Registry 错误、配置执行容量 6，首页 200。
- 独立复跑后端 `70 passed`（仅有测试框架弃用警告及退出时临时目录权限提示，测试
  退出码为 0），项目虚拟环境 Ruff 检查 backend 通过，前端 `typecheck` 与生产构建
  通过，`git diff --check` 无空白错误。
- 本地实现验收通过；未使用真实 MiniMax API Key，因此真实 `/models`、Tool Calling
  和运行态请求仍属于持有人凭据验证项。当前改动未提交，未运行财务任务。

## 2026-08-06 · 关闭 Gitee Skill 定时同步

- 已确认 Windows 计划任务 `Finance Skill Gitee Sync` 对应
  `scripts/sync_from_gitee.ps1`，操作前状态为 Ready，未在运行。
- 已禁用该计划任务并复查 `Enabled=False`；任务定义保留，平台服务、Worker 和其他
  Windows 计划任务未改动。此后不会再按小时自动拉取最新 Skill，手工运行同步脚本
  仍然可用。

## 2026-08-06 · 已完成工作流仍显示转圈的诊断

- 截图对应任务 `30caa6ae-1716-49fd-b1ee-9ed141f67f1f` 已在数据库中完成：
  `stage=completed`、`state=succeeded`、`progress=100`，完成信息和产出均已保存，
  不是后端仍在写表。
- 原因是 `frontend/src/pages/WorkflowChat.tsx` 用
  `workflow.state === 'completed'` 判断完成，而后端成功状态实际为 `succeeded`；页面
  收到 `stage=completed` 后停止轮询，但 `completed` 仍为 false，所以加载图标一直显示。
  页面顶部的 `核销执行中` 也是固定文案。
- 本次按用户要求只诊断、未修改代码。建议以 `stage === 'completed'`（并兼容
  `state === 'succeeded'`）作为完成条件，同时让顶部状态文案按完成/失败/执行中切换，
  增加工作流成功响应的前端回归测试。

## 2026-08-06 · 修复已完成工作流仍显示转圈

- `frontend/src/pages/WorkflowChat.tsx` 的完成条件改为同时识别
  `stage === 'completed'` 与 `state === 'succeeded'`，与后端成功状态一致；完成后
  图标、标题、时间线最后一步和状态提示都会进入完成态。
- 顶部固定文案 `核销执行中` 改为按失败、完成、执行中动态显示，成功任务显示
  `核销已完成`。
- 验证：前端 `npm run typecheck`、`npm run build` 均通过；运行实例首页和新版前端
  bundle 均返回 200，已确认 bundle 包含新完成条件及 `核销已完成`、`核销任务已完成`
  文案。未修改任务数据或重新执行核销。

## 2026-08-07 · 更新 Codex CLI

- 当前 CLI 通过 npm 全局安装，原版本为 `@openai/codex@0.146.0`。
- `codex update` 首次执行因 npm 持久代理 `127.0.0.1:7897` 拒绝连接而失败；随后仅对
  本次命令临时使用官方 registry `https://registry.npmjs.org`，未修改持久 npm 配置。
- 已完成 `npm install -g @openai/codex@0.146.1`，当前 `codex --version` 输出
  `codex-cli 0.146.1`，`codex --help` 与 `codex update --help` 均可正常启动。

## 2026-08-06 · 同步当前应收核销 Skill

- 按用户授权，使用 `scripts/sync_finance_skills.py` 的单 Skill 同步入口，从
  `D:\BESTEASY\finance-skills\skills\ar-hexiao-daily` 重新生成平台
  `skills/ar-hexiao-daily`；其它平台 Skill 未修改。
- 平台清单保持 `1.5.0 / published / workflow`。旧取数标识已统一为
  `2026-08-05-order-written-off-fallback-v2`，员工说明使用当前日清和写前校验通过后
  直接写工作副本的规则。
- 平台包46个文件与隔离生成包 SHA-256 完全一致，Skill 结构校验通过，
  `backend/tests/test_workflow.py` 为 `8 passed`。一次同时运行 workflow 与 platform_e2e
  时，模型连接列表测试受同一测试会话前序数据影响失败，与本次 Skill 同步无关；
  未使用真实凭据或运行财务任务。

## 2026-08-10 · 项目明细补录轻量化

- `project-detail-to-ledger` 已更新为 `1.1.0`。平台 vendor 与安装版、知识库源码同步：
  最终工作簿不再设置打开时完整重算，历史外链公式固化为现有缓存值并移除外链部件，
  内部公式保留计算链，只清除范围发生变化的公式缓存。
- 同时修复中文 sheet 名在 OOXML 中转义后无法识别，以及单行范围 `L2:L2` 被错误改成
  `L3:L3` 的问题；现在只延长范围终点。
- 三份 Skill 结构校验通过，项目明细补录专项测试2项与项目级联合回归共12项通过；
  隔离同步成功生成 `1.1.0` 平台包，vendor 两个核心脚本与安装版哈希一致。
- 使用真实形状工作簿只读基线和合成追加行验证：源文件哈希不变，12个sheet可读，
  237个历史外链公式被固化，外链部件0，计算链保留，强制重算标记0；原表样式部件逐字节保留，
  输出通过OpenXML格式校验。未运行真实平台任务，未提交或推送。

## 2026-08-10 · 应收核销 Skill 旧版本清理

- 使用 `scripts/sync_finance_skills.py` 的单 Skill 入口，将平台 `ar-hexiao-daily` 更新为当前源码；只重建该 Skill，未同步其它平台 Skill。
- 平台 vendor 的 `classify_hexiao.py` 与源码 SHA-256 均为 `C83A7D54963218007CCAD18A7EC3EEB1060CC46177E245EC7D4645ED9F512176`，取数标识为 `2026-08-05-order-written-off-fallback-v2`；Skill 结构校验通过，工作流测试 `8 passed`。
- 平台 `.codex`、`.skill-sync` 和 `data/backups/skill-sync` 中的旧 `ar-hexiao-daily` 副本已移入 Windows 回收站；活动平台包和运行数据未删除。定时 Gitee 同步任务仍保持禁用。

## 2026-08-13 · 启动财务 Skill 平台

- 默认端口 `8000` 已由另一套 Python API 服务 `apps/api/server.py` 占用，未停止或修改该服务；平台改用空闲端口 `8001`，通过 `scripts/start.ps1` 以 `0.0.0.0` 和 6 个 Worker 启动。
- 回读验证：本机首页返回 200，回环及有线局域网健康接口均为 `status=ok`；注册 19 个 Skill、0 个 Registry 错误，Python 2、HTTP 2、Workflow 2 个 Worker 的 PID 和命令行均匹配。
- 访问地址：本机 `http://127.0.0.1:8001`，有线局域网 `http://192.168.20.207:8001`。未运行财务任务，未使用或输出任何凭据。

## 2026-08-13 · 临时外网访问入口

- 平台本身继续监听 `8001`；在 `127.0.0.1:8011` 增加独立 Basic Auth 反向代理，再通过 Pinggy 官方 SSH 443 隧道发布临时 HTTPS 地址。免费隧道提示有效期 60 分钟，进程或电脑停止后地址立即失效。
- 网关删除外部请求中的 `Authorization` 与 `X-User-*` 身份头，固定向平台传递 `finance_user / public-gateway-user`，并拒绝 `/admin`、`/admin/*`、`/api/admin/*`；认证口令仅在网关进程环境和本次用户交付中使用，未写入项目上下文或日志。
- 公网回读验证：无认证为 401，正确认证首页 200，`/api/health` 为 `ok`、19 个 Skill、0 个 Registry 错误；伪造 `X-User-Role: skill_admin` 后 `/api/session` 仍返回 `finance_user`，管理员页面返回 403。
- Cloudflare Tunnel 官方二进制下载因网络缓慢未完成且续传文件损坏，未执行该文件；最终未使用 Cloudflare Tunnel。未运行财务任务，未改业务数据，未提交或推送代码。

## 2026-08-13 · 员工工作台与安全改造实施文档

- 新增 `docs/EMPLOYEE_WORKBENCH_MVP_IMPLEMENTATION.md`，把“工具驱动、AI 生成不可执行任务草稿、员工确认后运行”的产品方案拆分为认证、用户级隔离、TaskDraft、默认模型档案、统一向导、审批、审计、网络出站限制和应收核销恢复发布等开发任务。
- 文档列出具体新增/修改文件、数据库迁移、接口、28项 P0/P1/P2 任务、依赖关系、测试文件和验收证据；10个工作日仅定义为内网、3～5个只读或生成副本 Skill、写入 Skill 全部禁用的受限 MVP，完整部门试用版预计15～20个工作日。
- 明确当前阻断项：浏览器身份头不可信、资源读取主要按部门而非所有者隔离、无通用审批模型、`ar-hexiao-daily` 仍为 published 且无需确认、Manifest 网络白名单尚无不可绕过的执行层强制。本文仅新增规划文档，未修改平台代码、Skill 状态、数据库、业务文件或运行任务。

## 2026-08-13 · P0 安全基础二次评审修复

- `bootstrap.ps1` 不再对无版本旧库直接执行裸 `alembic upgrade head`，改为备份成功后调用统一 `init_db()` 接管入口；真实数据库备份副本从 11 张旧表成功升级到当前 head `8dd3d2f9a6c5`，认证三表和独立管理员初始化均通过。
- 旧库迁移测试会在基线建库后删除 `alembic_version`，真实覆盖“有业务表、无版本表”分支，并断言最终版本等于当前 Alembic head。
- 带 `--include-keys` 的备份分别校验主清单和高敏恢复清单；PowerShell 包装器新增 `-IncludeKeys`。普通员工改密不再删除 bootstrap 管理员的一次性密码文件。
- 验证：后端 91 项通过；Ruff 对本轮后端、迁移和备份脚本范围检查通过；前端 typecheck/build 通过。主实例未重启，真实数据库未迁移，仍需按实施文档执行受控部署。

## 2026-08-13 · P0-05 员工 Skill 权限

- 新增默认拒绝的 Skill 授权服务和管理员用户接口。普通员工只有写入 `user_skill_permissions` 且 `can_run=true` 的已发布 Skill 才能在目录中看到并创建任务；管理员按角色拥有全部管理权限。
- 标准任务、工作流、批次、文件绑定、参数解析、确认、对话推进和失败重试均增加服务端权限硬闸；撤权后等待确认任务不能继续。禁用员工会立即撤销既有会话。
- `/admin` 页面可创建员工、逐项授权、保存权限和启停账号。`can_create_draft` 与 `requires_approval` 只保存权限配置，分别等待 P1-03 和 P2 接入；权限变更已接入 P0-08 审计。
- 新增 8 项权限矩阵，后端全量 99 项通过；Ruff 指定范围、`git diff --check`、前端 typecheck/build 通过。验证仅使用隔离测试库，真实主实例和真实数据库未重启或迁移。

## 2026-08-14 · Next.js 迁移阶段二 Clerk 身份桥接

- 当前 Next.js 项目新增完整迁移实施文档，并明确保留 Next.js、shadcn/ui、主题和 Clerk 作为唯一前端，`financial_pj` 继续承担 FastAPI、业务权限、Skill、任务、文件、审计和 Worker。
- 后端新增 Clerk Session JWT 验证：仅接受 RS256，校验 issuer、时间声明、可选 audience 和 authorized party；Token 只用于取得 Clerk `sub`，平台角色、部门和 Skill 权限仍从本地数据库读取。无效 Bearer 在 hybrid 模式下不会退回旧 Cookie。
- `users` 增加唯一 `clerk_user_id` 与可选 `clerk_organization_id`，Alembic head 更新为 `b1a76f93c2de`。管理员用户接口可显式绑定或解除 Clerk 身份并记录脱敏审计；未绑定、组织不一致或禁用用户均被服务端拒绝。
- 认证支持 `session`、`hybrid`、`clerk` 三种显式模式。现有运行环境默认保持 `session`；完成 issuer、authorized party 和管理员 Clerk ID 配置后才切换 `hybrid`，新前端验收后再切换 `clerk`。
- 新增 8 项 Clerk 认证测试，覆盖真实 RSA 签名、authorized party、用户映射、组织限制、禁用用户、管理员绑定、Cookie 降级防护和仅 Clerk 模式。后端完整测试 120 项通过；仅有既有 Starlette/httpx 弃用警告和 Windows pytest 临时目录退出提示，退出码为 0。
- 当前 Next.js 新增服务端平台客户端和显式 `/api/platform/session` BFF 路由，使用 Clerk `auth().getToken()` 向 FastAPI 传递 Bearer Token；后端地址只使用服务端环境变量。Next.js 类型检查、lint 和生产构建通过，构建产物包含该动态路由；lint 仍有 5 条既有嵌套组件警告。
- 本次未读取、输出或写入任何 Clerk 密钥，没有迁移真实数据库、绑定真实 Clerk 用户、重启平台、运行财务任务或修改业务文件。检查时 `127.0.0.1:8001` 不可用；真实 Clerk 联调和运行实例切换仍待受控部署。

## 2026-08-14 · Clerk 管理员身份受控部署

- 部署前确认 Clerk 应用与平台均只有一个候选账号，但原 Clerk 测试用户并非目标邮箱；随后通过 Clerk Backend API 创建目标邮箱的应用用户并启用密码登录，最终仅把该用户绑定到平台唯一启用管理员 `admin`，原 Clerk 测试用户未删除且不再拥有平台映射。
- 真实 SQLite 数据库部署前已通过在线备份 API 备份并校验，备份目录为 `data/backups/20260814_103107_pre-clerk-binding`；数据库迁移从 `c4d91f7b2e10` 升级到 Clerk 身份版本 `b1a76f93c2de`，身份绑定变更已写入审计事件。
- 运行配置使用被 Git 忽略的 `.env.runtime.local`，设置 `FINANCIAL_AUTH_MODE=hybrid`、当前 Clerk issuer，以及 `http://localhost:3000`、`http://127.0.0.1:3000` 两个 authorized party；不复制或保存 Clerk Secret Key。`serve_control.py` 启动时在现有 `.env` 后加载该本地运行配置。
- 平台已在 `127.0.0.1:8001` 启动，API 与 6 个 Worker 的 PID、命令行均匹配；健康检查为 `ok`，19 个 Skill、0 个 Registry 错误。无 Bearer 请求继续进入旧 Session 登录，无效 Bearer 明确按 Clerk 拒绝，不会降级到 Cookie。
- Clerk 目标用户的密码启用、未锁定、未封禁，并通过官方密码校验接口验证；浏览器尚未代用户创建登录会话。后端完整测试 120 项和指定 Ruff 检查通过，只有既有 Starlette/httpx 弃用警告及 Windows pytest 临时目录退出提示。未运行任何真实财务任务，未提交或推送代码。

## 2026-08-14 · 迁移阶段三契约与阶段四 Skill 目录

- 新增根级 `CONTEXT.md`，固定平台用户、Skill、任务、任务事件、平台文件、任务草稿、审批记录和审计事件的业务含义；Clerk 用户只提供外部身份，平台用户继续承载本地角色、部门和权限。
- 新增 `backend/app/contracts.py` 和确定性 OpenAPI 导出脚本。OpenAPI 版本更新为 `0.2.0`，核心领域 DTO、员工/管理员 Skill DTO、任务摘要/详情 DTO 和后续 TaskDraft/ApprovalRecord 契约均进入 `components.schemas`；导出文件的 `--check` 可检测漂移。
- `/api/session`、健康检查、Skill、文件上传、任务摘要/详情和 Registry 重载补齐显式响应模型；新增 `/api/catalog/skills` 与详情接口，管理员和员工都只收到员工安全字段，handler、runtime、permissions、source 和 skill_hash 不进入目录响应。
- Next.js 已保存同一 OpenAPI 快照并用 `openapi-typescript 7.12.0` 生成类型；新增 Skill 目录与详情 BFF 和页面。后端完整测试 124 项、指定 Ruff、Next.js 契约检查、typecheck、lint 和生产构建通过；lint 仍为 5 条既有警告，构建仍有字体 fallback 与 `metadataBase` 既有警告。
- 重启前确认 runs、workflow_sessions 和 workflow_actions 均无活动记录；平台已安全重启到 `127.0.0.1:8001`，19 个 Skill、0 个 Registry 错误、6 个 Worker，7 个进程命令行均匹配。匿名目录请求返回 401。未运行真实 Skill，未修改业务文件，未提交或推送代码。

## 2026-08-14 · Clerk 管理员账号重新绑定

- 浏览器登录使用了另一个 Clerk 应用账号，登录成功后平台返回“身份尚未绑定”。经 Clerk Backend API 精确查询确认该账号唯一存在；绑定前检查显示它不是平台用户，而唯一启用管理员仍绑定旧 Clerk 身份。
- 修改前使用 SQLite 在线备份 API 生成 `data/backups/20260814_113334_pre-clerk-admin-rebind-db`，数据库完整性检查为 `ok`，SHA-256 写后回读一致。一次完整数据目录备份因运行期文件在复制时消失而失败，未作为有效备份使用；其不完整目录为 `data/backups/20260814_113315_pre-clerk-admin-rebind`。
- 通过平台本地管理员登录和 `/api/admin/users/{user_id}` 接口把唯一启用管理员 `admin` 的 Clerk 身份替换为本次登录账号；没有设置 Clerk 组织限制。旧 Clerk 身份随字段替换解除平台映射。
- 写后检查通过：目标身份映射到启用的 `skill_admin`，启用管理员总数为1、Clerk 身份绑定总数为1，并存在 `clerk_identity_changed=true` 的用户更新审计事件。未输出或保存登录密码，未运行任何 Skill，未提交或推送代码。

## 2026-08-14 · Next.js 迁移阶段四端到端验收

- 使用 Clerk 已绑定管理员和两份三行合成 Excel，在 Next.js 前端完成 `reconcile-bank` 的目录、详情、上传、参数确认、任务创建/确认、Worker 执行、SSE、结果展示和下载全链路验证；未使用真实财务文件。
- 验收任务 `1d010e6b-1b8a-412a-aae6-ec6b32257422` 成功结束，结果为银行流水3条、总账3条、成功匹配2条、两侧各1条未匹配；结果工作簿三个工作表经独立回读与渲染检查一致。
- 下载产生 `file.download` 成功审计，详情仅含文件类型、任务 ID、大小和 SHA-256，不含文件名或内容。后端 `test_platform_e2e.py` 4项通过。
- 验收发现并修复 Next.js 终态任务页跳过历史 SSE 的问题；刷新后完整展示10条事件。阶段四已经完成，下一阶段为工作台、任务中心和文件中心。

## 2026-08-14 · Next.js 迁移阶段五工作台与资源中心

- 新增员工工作台聚合接口，按当前用户或管理员部门范围统计待确认、执行中、成功、失败和文件数量，并返回常用 Skill、待处理任务、最近结果与最近文件；员工响应继续使用安全 Skill DTO，不含执行入口和来源路径。
- 任务列表改为服务端分页，任务摘要和详情返回业务失败原因、受控重试状态与阻断原因。失败或超时的只读任务可以创建新的重试任务；重试重新校验权限、Skill 版本、输入文件存在性和 SHA-256，同一来源任务的重复请求保持幂等，写入型任务不能直接重试。
- 新增文件分页、详情、保留日期和引用信息。默认保留日期为创建后90天，本阶段只展示日期，不自动清理；结果文件和任何已被任务或工作流引用的上传文件不能单独删除。通用文件下载沿用所有者检查、存储根目录检查和脱敏 `file.download` 审计。
- Next.js 已把原模板模拟概览替换为真实工作台，任务中心增加状态筛选、分页和失败定位，新增文件中心及导航入口，并通过明确列出的 BFF 访问 FastAPI。
- 后端全量127项测试通过，OpenAPI 快照一致；Next.js 类型检查、契约检查、定向 lint 和生产构建通过。浏览器使用现有 Clerk 管理员登录态验收三个页面，工作台显示1个成功任务和48个可见文件，文件中心显示3页数据及引用删除限制。
- 部署前确认无活动 Run、Workflow Action 和执行中 Workflow；平台安全重启后为 `development / ok`、19个 Skill、0个 Registry 错误、6个 Worker。未创建新任务，未删除或下载真实文件，未提交或推送代码。

## 2026-08-14 · Next.js 迁移阶段九审批与写入硬闸

- 新增 `approval_records`、双人审批服务和管理员接口。写入工作流的 Skill 树、输入文件及磁盘哈希、业务工作区、校验后计划、财务副本和变更预览被绑定为不可变审批证据；审批过期或任一证据变化时自动失效并退回重新确认。
- 发起人不能审批自己的任务。批准后生成唯一绑定的 `apply_confirmed` Action，Workflow Worker 在领取和执行前分别重新验证审批人、有效期、Action 内容与当前证据。无审批写入动作被拒绝，写入失败不自动重试。
- 标准 Run 对写入、外部动作、修改上传文件或权限要求额外审批的 Skill 默认拒绝创建；Worker 也拒领遗留队列中的同类 Run，避免从旧接口或数据库绕过工作流变更预览。
- 新增应用级网络策略和测试：只接受精确完整域名，拒绝通配符、协议、端口、IP 与 localhost；HTTP Adapter、Skill 子进程环境、智云 Playwright 请求和 API 请求均执行检查。当前真实智云地址仍为内网 IP，基础设施出站隔离也未完成，因此 `ar-hexiao-daily` 保持 disabled。
- 后端全量155项、来源 Skill 智云取数10项、Ruff、OpenAPI 契约、Next.js 类型/lint/生产构建均通过。部署前无活动 Run、Workflow Action 或执行中 Workflow。
- 备份 `data/backups/20260814_154908_pre-stage9-approvals` 已校验数据库和142个业务文件，数据库 SHA-256 为 `35a6084025e3dda219e53f928f367a6b242e8e7597fb11fe90e737670b32f667`，普通备份未包含凭据密钥。真实库升级至 `a8b6d1c904fe`，8001 API 与6个 Worker 健康，19个 Skill、0个 Registry 错误。
- 阶段十继续完成 PostgreSQL、统一 HTTPS、Worker 进程外网络隔离、并发/回滚演练和合成数据写入全流程；通过前不恢复写入型 Skill。

## 2026-08-14 · 阶段十 PostgreSQL 与统一 HTTPS 部署

- SQLite 数据已迁移到 PostgreSQL 16，19 张初始业务表、136 行记录和59处路径转换通过逐表哈希复核；Alembic head 为 `a8b6d1c904fe`。SQLite 原库及切换前全量数据备份继续保留。
- 独立 Compose 项目运行 Next.js、FastAPI、PostgreSQL、Caddy 与6个 Worker。主机只监听 `127.0.0.1:8443`；数据库、API、Next.js 和 Worker 不映射主机端口，Worker 仅加入内部数据网络且无法访问公网。
- PostgreSQL 并发验证为6个领取线程仅1个成功；48个迁移文件均存在、SHA-256一致并位于容器数据根。合成 `reconcile-bank` 任务成功，结果摘要、输出文件哈希和工作表结构回读一致。
- 最终 PostgreSQL 备份 `data/backups/20260814_171432_postgres-verified` 已恢复到临时数据库，19张表、150行、迁移版本与逐表哈希一致。旧 SQLite API、Vite 与6 Worker 已完成回滚演练，之后重新切回容器栈。
- 后端全量158项测试通过；Next.js 类型、lint和生产构建通过。最终后端镜像 ID 为 `e9671b927384d1aef34467551964bd7e0f51e57de85a83fd3d92041f6a823b34`，前端镜像 ID 为 `33587fdca7b9d439cbee826714629f81fac07ec98666ed4f8ef549230390a8c1`。
- 两个脏工作树的最终源码回滚点为 `data/backups/20260814_174307_stage10-source-rollback-final`，bundle、patch、untracked ZIP与清单哈希均已校验，忽略文件及生产密钥未进入快照。
- 当前为本机受限部署。智云仍只有IP地址，真实业务FQDN、受信任证书、精确受控出站路径和管理员恢复发布批准未提供；`ar-hexiao-daily` 必须继续保持 disabled，不能用伪造域名规避策略。

## 2026-08-14 · 阶段十精确域名出站代理

- 新增 CONNECT-only 出站代理并部署到 Compose。代理容器加入 `data` 与 `edge` 网络，6 个 Worker 仍只加入 `internal` 数据网络；空业务白名单默认拒绝全部目标。
- Worker 直接公网连接返回 `Network is unreachable`，通过生产代理访问未批准域名返回403。隔离临时代理仅允许 `example.com` 时精确主机返回200，未列出的 `www.example.com` 返回403，验证后临时容器已删除。
- Skill 子进程改用最小环境，不再继承数据库连接串、PostgreSQL 密码、Clerk Secret 或模型 API Key；智云业务凭据继续只通过标准输入临时传递。
- 新增正式域名 Caddy 模板、公司证书模板和生产配置校验。后端完整184项测试、相关Ruff、Caddy模板解析、Compose解析、PostgreSQL并发探针和幂等合成任务均通过。当前后端镜像为 `d485a4e81a2cbcd98c7e6fbf29f8c2115db7cc3527096b37982fd09a249a5318`。
- 生产 PostgreSQL 中有1条已迁移的业务凭据记录，未读取或输出密文；生产 `.env` 没有账号密码变量，`FINANCIAL_ZHIYUN_BASE_URL` 与出站白名单继续为空。真实智云 HTTPS FQDN、证书信任和现场443放行验收完成前，`ar-hexiao-daily` 保持 disabled。

## 2026-08-14 · P2-05 内网精确目标联调

- 用户确认当前阶段采用内网联调模式。网络策略新增 `internal`：只允许 RFC1918 IPv4、HTTP 和显式端口；当前唯一目标为 `http://192.168.10.167:18880`。原 `strict` HTTPS FQDN:443 模式继续保留，供对外正式部署使用。
- 出站代理支持精确 HTTP 转发，重写 Host、删除代理认证和连接头，只开放 GET、HEAD、POST、OPTIONS；Skill 的 Playwright 路由与 API 请求继续按协议、IP、端口精确校验。Worker 仍只加入内部 `data` 网络，代理加入 `data` 与 `edge`。
- 生产 `.env` 已切换为 `FINANCIAL_NETWORK_POLICY_MODE=internal`，平台入口保持 `127.0.0.1:8443`。部署后 Worker 直连智云失败，经代理访问唯一目标返回 200；错误 IP、错误端口和 CONNECT 均返回 403。验证未提交账号密码，也未读取业务数据。
- 后端完整 198 项测试通过；相关 Ruff、Compose、生产配置、OpenAPI、Next.js 契约、类型检查和 lint 通过，lint 仅保留 5 条既有组件嵌套警告。新后端镜像为 `sha256:8c141b19c45309940e8cf0cbc2b2661663ef1265292fc8cb7e53bd52c4e9eea5`。
- API 与 6 个 Worker 健康，Health 回读 19 个 Skill、6 个执行容量、0 个 Registry 错误；PostgreSQL 并发探针和幂等合成任务再次通过。`ar-hexiao-daily` 仍为 disabled，下一步是 P2-06 只读真实取数与写入副本专项回归，随后由管理员决定是否恢复发布。

## 2026-08-14 · P2-06 智云真实只读取数

- 用户确认核销日期 2026-08-13 后，在 `worker-workflow-1` 中使用平台已加密保存的唯一智云凭据执行真实只读取数。凭据只在进程内临时解密并通过标准输入传递，没有进入命令行、环境变量、日志或对话。
- 内网精确目标代理取数成功，导出版本为 `2026-08-13-flow-sales-name-v4`，生成四件套和摘要共 5 个文件：回款记录 5 笔、22 个 SO、核销明细 22 行、订单明细 33 个 SOD；接口总数一致，缺项目交付日期、无关联订单和缺 SOD 均为 0。
- 取数目录为 `data/controlled-tests/p2-06-zhiyun-fetch-20260813-20260814T111426Z/工作区`。官方来源校验脚本记录 5 个 SHA-256 后立即 verify，全部未变化。
- 本次没有分类、生成日清、前置登记或写财务工作簿。P2-06 的真实只读取数部分已通过，仍需完成受控写入副本专项回归；`ar-hexiao-daily` 保持 disabled。

## 2026-08-14 · P2-06 受控写入副本专项回归

- 用户提供 2025、2026 两份年度盈亏表和一份 2026 年到账流转表；三个下载原件只读并完成复制前后哈希比对。平台改为保存和显式传递完整年度盈亏映射，年度表数量不设上限、每年只允许一份，也支持写往年表。
- 2026-08-13 写前结果为可写 9、挂账 1、冲突 0，实际目标年度均为 2026；盈亏写入 9 条并逐格回读一致，2025 年副本未改变。流转计划自动 2、手填 3，前置登记成功，状态阶段无额外变更。
- 写后重新分类和校验得到可写 0、幂等跳过 9、冲突 0；再次统一执行时三份工作簿哈希全部不变。三个下载原件哈希仍与回归前一致。
- 严格轻量审计只发现原件中已经存在的透视表部件告警，2025 年表另有既有外部链接告警；未发现本次写入新增的结构错误。到账流转表 artifact-tool 导入和渲染通过，大型盈亏表因复杂公式在 300 秒内未完成渲染。
- 回归目录为 `data/controlled-tests/p2-06-write-copy-20260813-20260814T112935Z/工作区`。P2-06 完成，`ar-hexiao-daily` 保持 disabled，等待 P2-07 管理员批准。
- 工作流专项 10 项、后端全量 200 项测试和 Ruff 通过。API、出站代理及 6 个 Worker 已重建并部署镜像 `sha256:93b44cccfc6d4aacfd1f26286dc1ba4f04601b1238a6fce841277e76f324c665`；API 健康检查通过，登录页返回 200。

## 2026-08-20 · 交付金额高于原应收的部分回款规则

- 当实际交付金额高于原始应收且累计回款尚未达到实际交付金额时，核销计划使用独立的 `preserve_baseline_blank_carry` 模式：历史原行保留原始应收，本次回款允许高于该基线，新增未结清行的应收及计提、回款、收款信息和差异保持空值，剩余未收只作为程序内部判断量。
- 后续回款可以继续命中应收为空的未结清承接行；同批多笔父回款按独立步骤写入，特殊模式不应用普通业务的 1 元结清尾差。累计等于实际交付金额时使用现有最终结清规则，累计超过时继续挂账；实际交付金额不高于原始应收的既有拆分守恒规则未变。
- 分类、写前校验、工作簿写入、写后回读、幂等检查和订单差异报告均支持该模式。写前校验还要求首行非空应收必须等于原始应收基线，只有后续承接行可以为空。
- 来源 Skill 与平台内置副本的三份核心脚本 SHA-256 分别一致。来源 Skill 全量测试 412 项通过、5 项跳过；相关三文件测试 155 项通过、2 项跳过，Ruff 和 Python 编译检查通过。测试只使用合成工作簿，未读取或写入真实财务文件，未运行真实核销任务，也未提交或推送代码。

## 2026-08-31 · 父回款超出订单金额时保留未分配余额

- 用户确认整笔和分笔回款的父总到账都可以高于订单交付额或核销合计。整笔回款继续按订单已核销金额优先、完整交付额兜底；父额不足订单金额合计超过 1 元时挂账，父额超出时允许处理并把余额留在父回款审计，不分摊进 SO/SOD。
- 修改源 Skill 的父额审计、写前校验、业务规则说明和回归测试；整笔/分笔超出金额统一记录 `unallocated_parent_amount` 或顺序分配审计。源 Skill 测试 466 passed、5 skipped；Ruff 检查仍有既有历史告警，未扩大范围处理。
- 源 Skill 与平台内置副本同步到版本 1.6.12。开发 API 重载注册表后健康检查为 development/ok、19 个 Skill、0 个注册表错误；API 和各 Worker 容器均回读到新脚本。未运行真实核销、未写入财务工作簿、未提交或推送代码。

## 2026-09-04 · 应收合并透视汇总兼容性修复

- 定位下载结果表打开时被 Excel 删除透视表的原因：透视字段中的空白项缺少对应 shared item 的 `x` 索引，且旧版透视缓存使用 `OFFSET` 动态名称作为数据源，当前 Excel 组合下无法稳定装载。
- 源 Skill 与平台内置副本改为 Excel 可识别的空白项编码，并将数据源改为 `主表!A1:Q1048576`，保留追加新行后手动刷新透视表的能力；同步后仅重启开发 API，生产环境未触碰。
- 使用不含真实业务数据的临时工作簿验证 Excel 打开、原生透视表存在及追加新行后刷新；另生成下载目录的修复副本，原损坏文件未覆盖。开发 API `/api/health` 返回 `status=ok`，无注册表错误。
- 未运行仓库测试；未执行真实财务任务，未提交或推送代码。
