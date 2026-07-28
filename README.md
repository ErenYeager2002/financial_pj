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

浏览器打开 `http://127.0.0.1:8000`。停止平台：

```powershell
.\scripts\stop.ps1
```

本地 `.env` 已支持阿里云百炼 OpenAI-Compatible 接口，当前模型为
`qwen3.7-plus`。模型只负责理解自然语言和生成受 Schema 约束的参数；
最终财务计算仍由确定性 Skill 完成。

也可以直接在网页的“模型接入”页面输入 API Key。平台会自动验证供应商、
读取支持 Tool Calling 的模型，并允许在每次 Skill 运行时选择具体模型。
API Key 使用服务端密钥加密保存，接口只返回脱敏后的末四位。

`ar-hexiao-daily` 使用对话式工作流：先确认核销日期和输入文件，后台生成
《核销日清》供员工下载检查；只有员工在会话中再次明确确认，Worker 才能执行
盈亏明细与流转安全子集写入。会话支持正常多轮问答，只有用户明确要求推进工作
时才触发 Tool Calling；模型不能直接生成或执行 Shell 命令。

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
