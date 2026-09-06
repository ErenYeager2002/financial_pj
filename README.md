# 财务 Skill 平台

面向财务部门的内部工具平台：员工选择 Skill、上传文件、描述要求，平台完成参数解析、校验、排队、确定性执行、实时进度、结果下载和审计留痕。

当前维护的界面位于 `web/`，使用 Next.js、Clerk 和服务端 BFF；FastAPI 位于 `backend/`，
负责本地平台用户、部门隔离、Skill 权限、任务状态、文件引用、审计和 Worker 协调。生产由
Next.js 容器提供页面，FastAPI 的静态页面回退仅用于兼容场景。本轮源码改动尚未部署。

Workflow 与 Pi Harness 在任务创建时固定执行方式、Skill 快照、业务日期和材料版本。应收核销
多日期按日期升序串行处理，写入前经过校验并使用隔离副本，回读或租约异常后不自动重试；模型
只通过统一的结构化、脱敏和分页接口读取任务资料。员工界面显示真实存在的确认阶段，Worker、
Pi Harness 和哈希等实现信息保留在管理或详情视图。

当前 Registry 共接入 19 个 Skill，实际发布状态以管理后台和健康检查为准。
已发布工具覆盖应收合并与拆分、劳务发票核对、合规抽查、申报表重命名、
追觅应收进度对比、部门费用分摊、九点下单统计、银行流水对账和对话式应收核销。
完整状态与暂缓发布原因见
[docs/FINANCE_SKILLS_CATALOG.md](docs/FINANCE_SKILLS_CATALOG.md)。

## 快速启动

生产环境需要 Docker Desktop；本地测试需要 Python 3.11+、Node.js 22+ 和 pnpm 10.15.1。

```powershell
Set-Location D:\BESTEASY\financial_pj
.\.venv\Scripts\python.exe .\scripts\prepare_production_env.py --check
.\scripts\start.ps1 -Build
```

本机浏览器打开 `https://localhost:8443`。默认只监听 `127.0.0.1`，PostgreSQL、
FastAPI、Next.js 和 Worker 不映射主机端口。不要通过公网隧道传输真实财务文件。

停止平台：

```powershell
.\scripts\stop.ps1
```

## 开发模式

频繁修改前端、后端或 Skill 时使用开发模式。它使用独立的 PostgreSQL 卷和
`data/development` 文件目录，不读取生产数据库和生产平台文件；真实应收核销默认关闭。
默认只启动 PostgreSQL、FastAPI 和 Next.js，前后端会监听本地源码变化，普通代码修改不需要重新构建镜像。执行任务时再按需启动 Worker 和受控外联代理。

Windows 下也可以双击项目根目录中的 `启动财务Skill平台.exe`。启动器默认使用本机
Turbopack 前端和 Docker 开发后端，可按需勾选任务 Worker，启动完成后会打开浏览器；
停止操作保留开发数据。重新生成启动器时运行：

```powershell
.\scripts\build-dev-launcher.ps1
```

首次启动会从本机 `deploy/production/.env` 复制数据库等连接配置到 Git 忽略的
`deploy/development/.env`，不会复制生产数据：

```powershell
Set-Location D:\BESTEASY\financial_pj
.\scripts\dev.ps1 -Build
```

以后启动或查看代码修改：

```powershell
.\scripts\dev.ps1
```

浏览器打开 `http://localhost:3000`，API 健康检查为
`http://localhost:8000/api/health`。普通源码修改会自动更新；只有修改
`backend/pyproject.toml`、Dockerfile 或系统依赖后才需要再次使用 `-Build`。

日常使用平台时，先在终端一构建并启动生产前端；需要调试热更新时，再在终端二使用 3001 端口：

```powershell
corepack pnpm --dir web build:webpack
.\scripts\start-frontend-prod.ps1
```

终端二：

```powershell
.\scripts\dev-frontend-hot.ps1
```

停止热更新服务：`.\scripts\dev-frontend-hot.ps1 -Stop`。

生产前端使用 3000 端口，热更新调试使用 3001 端口，并使用独立的 `.next-hot` 构建目录；两者不要同时占用同一个端口。
启动生产前端前先停止 `dev.ps1` 启动的 3000 端口本机前端。

需要让同一局域网内的电脑临时访问开发平台时，使用显式的局域网模式。下面的示例以
`WLAN` 网卡为例，平台会根据该网卡的 IPv4 地址生成访问地址：

```powershell
.\scripts\dev.ps1 -Mode Tasks -Lan -LanInterfaceAlias WLAN
.\scripts\enable_lan_access.ps1 -Port 3000 -InterfaceAlias WLAN
.\scripts\enable_lan_access.ps1 -Port 8000 -InterfaceAlias WLAN
```

其他电脑访问启动输出中的 `http://局域网IP:3000`。Clerk 开发实例必须允许该局域网 origin；
修改配置后重新运行 `.\scripts\dev.ps1`，
平台会恢复为只监听本机。局域网模式只允许专用网络的 LocalSubnet，禁止通过路由器端口
转发、frp、ngrok 或其他公网隧道暴露平台。
需要调试 Skill 或后台任务时运行：

```powershell
.\scripts\dev.ps1 -Mode Tasks
```

任务 Worker 不随源码或 Skill 文件保存自动重启，避免中断核销和文件处理。需要加载 Worker 修改时，先确认没有正在执行或排队的任务，再运行：

```powershell
.\scripts\dev.ps1 -RestartWorkers
```

新增、删除或移动 Next.js 路由后如果页面仍显示旧的 404，可只重置可再生的前端缓存：

```powershell
.\scripts\dev.ps1 -ResetFrontendCache
```

停止开发环境并保留开发数据：

```powershell
.\scripts\dev-stop.ps1
```

`-RemoveData` 只删除开发 Docker 数据卷，不会删除 `data/development`。开发模式仅用于
调试，不要上传或处理真实财务文件。

生产拓扑和正式域名配置见 [deploy/production/README.md](deploy/production/README.md)。
部署包必须排除本机 `.env`、`data/`、`.venv/`、`web/.env*` 和历史财务文件。

平台默认按执行池启动 6 个 Worker：Python 2、HTTP 2、Workflow 2。不同 Skill
可以并行执行；同一个 Skill 的并发数由 `tool.yaml` 中
`runtime.concurrency_limit` 控制。RPA 默认不启动，启用时建议保持 `rpa:1`。
Worker 使用数据库原子领取、执行租约和心跳，避免重复领取；只读任务在 Worker
异常退出且租约过期后最多自动重试一次，高风险写入和工作流动作不会自动重试。

本地 SQLite 已启用 WAL 和忙等待，适用于部门内网的小规模并行。正式多机部署仍
建议将 `FINANCIAL_DATABASE_URL` 切换为 PostgreSQL。

本地 `.env` 已支持阿里云百炼 OpenAI-Compatible 接口，当前模型为
`qwen3.7-plus`。模型只负责理解自然语言和生成受 Schema 约束的参数；
最终财务计算仍由确定性 Skill 完成。

也可以直接在网页的“模型接入”页面输入 API Key。平台会自动验证供应商、
读取支持 Tool Calling 的模型，并允许在每次 Skill 运行时选择具体模型。
API Key 使用服务端密钥加密保存，接口只返回脱敏后的末四位。

`ar-hexiao-daily` 使用表单式工作流：安全保存一次智云账号，上传两份财务工作簿，
并选择 1～7 个核销日期。平台为多日期请求创建一个批次和多个单日任务，按日期
从早到晚串行执行；前一天写入和回读成功后的工作副本会作为下一天输入。任一天
失败时批次暂停，可从失败日期继续，已经成功的日期不会重复执行。Worker 使用
本机 Edge 自动登录智云并只读取数；账号密码使用服务端密钥加密保存，不进入模型
上下文、任务参数、命令行、环境变量或日志。日清与写前校验通过后，仅写隔离工作
副本，并分别输出每日结果和订单差异表。

在开发环境无法连接公司内网时，可以在应收核销创建页的“取数来源”中选择“使用已有取数快照”。
平台只会列出当前账号自己保存、校验通过的 v5 四件套；选择快照和日期后，仍按原流程检查取数、
执行核销和写前校验，符合条件后自动写入隔离工作副本。快照模式不会读取智云凭据，也不允许按编号补取智云数据。
开发 Compose 默认开启快照回放；生产环境保持关闭。

## 目录

```text
financial_pj/
├── web/                         Next.js、shadcn/ui 与 Clerk 用户界面
├── backend/                     FastAPI、Worker 与 Alembic
├── skills/                      经审核的运行 Skill
├── sources/finance-skills/      Skill 原始源码及上游历史
├── contracts/                   OpenAPI 契约
├── deploy/                      Compose、Caddy 与容器配置
├── scripts/                     初始化、备份、迁移和发布脚本
├── tools/                       项目专用校验工具
└── data/                        数据、上传、备份和手工作业区；Git 忽略
```

架构与完整业务流程见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，新 Skill 接入方式见 [docs/SKILL_CONTRACT.md](docs/SKILL_CONTRACT.md)。

同步 `finance-skills` 仓库中的已审查版本：

```powershell
.\.venv\Scripts\python.exe .\scripts\sync_finance_skills.py `
  --skill-id ar-hexiao-daily
```

同步脚本只复制业务说明、脚本、配置和参考资料；会排除测试缓存、工作区、
历史输出、浏览器账号配置和本地凭据。同步后的 Skill 自包含在本仓库中，
运行时不会直接执行远程 GitHub `main` 分支。

### 从 Gitee 定时同步（Windows）

自动同步使用独立检出目录 `.skill-sync\finance-skills`，每次更新前会备份
`skills`，同步失败自动恢复；只有检测到新提交时才会重启正在运行的平台。
如果远端缺少可执行 Skill，同步会中止；如果只缺少目录级 Skill，则保留平台现有版本并记录提示。
先手动验证一次：

```powershell
.\scripts\sync_from_gitee.ps1
```

验证通过后，以当前用户权限创建每小时任务（任务计划程序也可以修改这个频率）：

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument `
  "-NoProfile -ExecutionPolicy Bypass -File D:\BESTEASY\financial_pj\scripts\sync_from_gitee.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
  -RepetitionInterval (New-TimeSpan -Hours 1) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "Finance Skill Gitee Sync" `
  -Action $action -Trigger $trigger -Description "同步已审查的 finance-skills 到财务 Skill 平台" `
  -RunLevel Limited
```

不要把 Gitee Token 或其他凭据写进脚本；当前仓库为公开仓库，若以后改为私有仓库，
应使用 Windows 凭据管理器或 SSH Deploy Key。服务器端不要直接复用此任务，
应在服务器上单独配置 systemd timer，并先完成本机验证。

## GitHub Skill

Skill 可以存放在私有 GitHub 仓库，但平台运行的是经过批准的 tag/commit 和任务快照，不应在任务开始时直接执行远程 `main` 分支。可通过 `FINANCIAL_EXTERNAL_SKILL_DIR` 指向已经同步和审查的本地工作树。

## 历史验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest backend
.\.venv\Scripts\python.exe -m ruff check backend skills --config backend\pyproject.toml
Set-Location web
pnpm contracts:check
pnpm typecheck
pnpm build
```

并行执行的隔离端到端检查：

```powershell
.\.venv\Scripts\python.exe .\.codex\parallel-runtime-check.py
```
