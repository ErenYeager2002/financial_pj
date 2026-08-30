# 开发模式

Status: resolved

## 目标

为财务 Skill 平台增加与生产部署隔离的开发模式。开发模式直接挂载本地源码，
Next.js 与 FastAPI 自动热更新，Worker 在源码变化后自动重启。生产 Compose、生产数据
和生产启动入口保持不变。

## 公开入口

- `scripts/dev.ps1`：校验并启动开发环境；默认在 Windows 本机运行 Turbopack 前端，
  支持 `-Frontend Docker` 回退，以及 `-Build`、`-ValidateOnly`、
  `-RestartWorkers` 和 `-ResetFrontendCache`。
- `scripts/dev-frontend-host.ps1`：管理本机 Next.js 与 Agent Runtime 监听进程、
  依赖指纹、PID 和停止操作。
- `scripts/dev-stop.ps1`：停止开发环境，默认保留开发数据；显式传入 `-RemoveData`
  才删除开发卷。
- `启动财务Skill平台.exe`：Windows 图形启动器，调用现有开发启动和停止脚本；可选启动
  任务 Worker，并在成功后打开浏览器。源码位于 `tools/windows-launcher`，通过
  `scripts/build-dev-launcher.ps1` 重新生成。
- `scripts/validate_development_mode.py`：不启动服务，只验证开发 Compose 与脚本的
  安全约束。

## 必须满足

- 开发服务只绑定 `127.0.0.1`。
- 开发数据库和平台文件不复用生产数据。
- 默认关闭真实应收核销执行。
- 前端默认在宿主机使用 `pnpm dev` 与 Turbopack，API 使用容器内的
  `uvicorn --reload`；Docker Webpack 仅作为兼容回退。
- Worker 使用源码监听重启，不需要因普通 Python/Skill 修改重建镜像。
- 本机前端安装依赖和构建 Agent Runtime 时不向子进程传入 Clerk 密钥；运行前端时才注入。
- 本机前端就绪检查必须确认 3000 端口属于本次启动的进程树；超时或异常退出后清理该进程树。
- 依赖文件或 Dockerfile 变化时才需要 `scripts/dev.ps1 -Build`。
- 开发模式通过 `http://localhost:3000` 访问，API 调试地址为
  `http://localhost:8000`。

## 验证结果

- 配置验证、Compose 展开、PowerShell 语法、Pytest 和 Ruff 通过。
- API 健康检查返回 `environment=development`。
- 登录页返回 HTTP 200。
- FastAPI 与三个 Worker 已通过临时源码探针验证自动重载。
