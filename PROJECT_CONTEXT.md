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
- `skills/`：平台托管 Skill；当前示例为 `reconcile-bank`。
- `data/`：上传、运行快照、输出、日志和数据库，不进入 Git。
- `docs/`：架构与 Skill 接入协议。
- `scripts/`：初始化、启动和停止脚本。

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
