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
- `skills/`：平台托管 Skill；共登记 18 个，其中 9 个 published、2 个 draft、
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
- RPA Worker 由 `FINANCIAL_WORKER_POOLS` 控制，默认仍只启用 `python,http`。
