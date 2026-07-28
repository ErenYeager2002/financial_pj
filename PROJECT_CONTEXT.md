# 项目上下文

## 项目目标

部门内部财务 Skill 运行平台。员工从网页选择已发布 Skill，上传文件并用自然语言描述要求；大模型只负责参数理解与结果解释，确定性脚本、RPA 或内部 API 负责真实执行。

## 权限约定

- `finance_user`：运行所有已批准的 Skill、上传和下载本部门文件、确认和取消任务。
- `skill_admin`：除普通权限外，可刷新、维护和发布 Skill。
- 写 ERP、提交凭证、付款、外发等高风险动作需要运行前确认；只读分析可直接执行。

## 技术结构

- `backend/`：FastAPI、SQLAlchemy、SQLite、Registry、Orchestrator、Worker 与适配器。
- `frontend/`：React + TypeScript + Vite。
- `skills/`：平台托管 Skill；共登记 18 个，其中 10 个 published、1 个 draft、
  7 个 disabled。状态明细见 `docs/FINANCE_SKILLS_CATALOG.md`。
- `data/`：上传、运行快照、输出、日志和数据库，不进入 Git。
- `docs/`：架构与 Skill 接入协议。
- `scripts/`：初始化、启动和停止脚本。
- 模型接入：普通用户可在前端只输入 API Key，后端自动验证百炼并读取支持
  Tool Calling 的千问模型；API Key 加密存放在 SQLite，主密钥位于
  `data/credential.key`，前端只显示脱敏提示。
- 任务模型：用户可在每次 Skill 运行时选择连接与模型，运行审计保留供应商和模型名。

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
Set-Location frontend
npm run typecheck
npm run build
```

## 当前边界

第一期使用演示身份请求头和 SQLite，适合单部门内网验证。正式部署前需要接公司 SSO、PostgreSQL、独立隔离 Worker、Git 批准版本同步、病毒扫描、日志脱敏和备份策略。

## 2026-07-28 · 写入后源文件校验修复

- `apply_confirmed` 现在先使用准备阶段快照执行写入前校验，再运行统一写入。
- 两份计划内工作簿均写入并通过脚本回读后，重新记录最终基线并立即复核，避免
  盈亏表写入后的中途快照把随后写入的到账流转表误判为外部改动。
- 写入后基线更新失败使用独立错误状态，页面会明确提示不要重复确认或重出日清，
  避免二次写入。
- 已恢复任务 `716f38e8-0018-4570-874a-d7621d6735a6`：跑批台账证明盈亏和
  流转均已写入，恢复过程只更新基线和任务产物登记，没有再次运行统一写入。

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
