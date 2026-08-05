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
