# 财务 Skill 运行平台

面向财务部门的内部工具平台：员工选择 Skill、上传文件、描述要求，平台完成参数解析、校验、排队、确定性执行、实时进度、结果下载和审计留痕。

当前 Registry 共接入 18 个 Skill：10 个已发布、1 个草稿、7 个停用。
已发布工具覆盖应收合并与拆分、劳务发票核对、合规抽查、申报表重命名、
追觅应收进度对比、部门费用分摊、九点下单统计、银行流水对账和对话式应收核销。
完整状态与暂缓发布原因见
[docs/FINANCE_SKILLS_CATALOG.md](docs/FINANCE_SKILLS_CATALOG.md)。

## 快速启动

需要 Python 3.11+、Node.js 20+。

```powershell
Set-Location D:\BESTEASY\financial_pj
.\scripts\bootstrap.ps1
.\scripts\start.ps1
```

本机浏览器打开 `http://127.0.0.1:8000`。平台默认只监听 `127.0.0.1`，
**不会**暴露到局域网或公网。完成身份认证评估前，不要通过公网隧道（frp /
ngrok / Cloudflare Tunnel 等）传输真实财务文件。

局域网试用是**显式开启**的：先用管理员 PowerShell 执行防火墙脚本，再显式
指定监听地址启动：

```powershell
.\scripts\start.ps1 -HostAddress 0.0.0.0
```

首次开启局域网访问时，请使用**管理员 PowerShell**执行：

```powershell
.\scripts\enable_lan_access.ps1
```

普通 PowerShell 也可以运行该脚本，系统会自动弹出管理员权限确认。
脚本默认把 WLAN 设置为专用网络，并且只在 WLAN 接口上允许同一子网访问
TCP 8000。请只在可信网络、且已经完成服务端身份认证之后启用；当前内部测试版
尚未接入正式的用户登录鉴权，同一 Wi-Fi 中知道地址的访问者可能看到任务和文件，
因此在正式认证上线前应保持 `127.0.0.1` 默认配置。

停止平台：

```powershell
.\scripts\stop.ps1
```

Linux 公网部署采用独立域名、HTTPS、Nginx 登录保护和 systemd 服务；完整步骤见
[deploy/README.md](deploy/README.md)。部署包必须排除本机 `.env`、`data/`、
`.venv/` 和历史财务文件。

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

## 目录

```text
financial_pj/
├── backend/        FastAPI 与 Worker
├── frontend/       React 工作台
├── skills/         可执行 Skill
├── docs/           架构与接入协议
├── scripts/        初始化和运行脚本
└── data/           本地数据库、上传、运行快照和日志
```

架构与完整业务流程见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，新 Skill 接入方式见 [docs/SKILL_CONTRACT.md](docs/SKILL_CONTRACT.md)。

同步 `finance-skills` 仓库中的已审查版本：

```powershell
.\.venv\Scripts\python.exe .\scripts\sync_finance_skills.py `
  --source D:\BESTEASY\finance-skills\skills
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

## 当前验证

```powershell
.\.venv\Scripts\python.exe -m pytest backend
.\.venv\Scripts\python.exe -m ruff check backend skills --config backend\pyproject.toml
Set-Location frontend
npm run typecheck
npm run build
```

并行执行的隔离端到端检查：

```powershell
.\.venv\Scripts\python.exe .\.codex\parallel-runtime-check.py
```
