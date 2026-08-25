# 开发模式

Status: resolved

## 目标

为财务 Skill 平台增加与生产部署隔离的开发模式。开发模式直接挂载本地源码，
Next.js 与 FastAPI 自动热更新，Worker 在源码变化后自动重启。生产 Compose、生产数据
和生产启动入口保持不变。

## 公开入口

- `scripts/dev.ps1`：校验并启动开发环境；支持 `-Build`、`-ValidateOnly` 和
  `-RestartWorkers`。
- `scripts/dev-stop.ps1`：停止开发环境，默认保留开发数据；显式传入 `-RemoveData`
  才删除开发卷。
- `scripts/validate_development_mode.py`：不启动服务，只验证开发 Compose 与脚本的
  安全约束。

## 必须满足

- 开发服务只绑定 `127.0.0.1`。
- 开发数据库和平台文件不复用生产数据。
- 默认关闭真实应收核销执行。
- 前端使用 `pnpm dev`，API 使用 `uvicorn --reload`。
- Worker 使用源码监听重启，不需要因普通 Python/Skill 修改重建镜像。
- 依赖文件或 Dockerfile 变化时才需要 `scripts/dev.ps1 -Build`。
- 开发模式通过 `http://localhost:3000` 访问，API 调试地址为
  `http://localhost:8000`。

## 验证结果

- 配置验证、Compose 展开、PowerShell 语法、Pytest 和 Ruff 通过。
- API 健康检查返回 `environment=development`。
- 登录页返回 HTTP 200。
- FastAPI 与三个 Worker 已通过临时源码探针验证自动重载。
