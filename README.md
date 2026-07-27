# 财务 Skill 运行平台

面向财务部门的内部工具平台：员工选择 Skill、上传文件、描述要求，平台完成参数解析、校验、排队、确定性执行、实时进度、结果下载和审计留痕。

当前内置“银行流水自动对账”示例，已经覆盖从 Excel 上传到结果工作簿下载的完整链路。

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
