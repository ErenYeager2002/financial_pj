# 阶段十本机容器部署

该拓扑把 Next.js、FastAPI、PostgreSQL、Python Worker、Pi Harness Agent Worker、精确目标出站代理和 HTTPS 网关放入独立 Compose 项目：

- 唯一主机入口是 `https://localhost:8443`；
- PostgreSQL、FastAPI、Next.js 和 Worker 均不映射主机端口；
- 运行时 Skill 使用独立 `skill-data` 持久卷；API 可原子发布，Worker 只读挂载；
- Worker 只加入 `internal` 数据网络，不能直接访问公网；需要联网的 Skill 子进程只能通过出站代理；
- 出站代理的 `strict` 模式只接受 HTTPS CONNECT，并按精确 FQDN 和 443 端口放行；`internal` 模式只允许显式配置的 RFC1918 IPv4、HTTP 协议和端口；空目标列表默认拒绝全部目标；
- 平台仅使用账号密码和服务端会话登录，浏览器只访问同一 HTTPS 入口；
- `ar-hexiao-daily` 可按任务选择 Workflow 或 Pi Harness；两种方式都只通过平台受控 Worker 执行真实取数和工作副本写入。

AI 助手生产默认使用服务端 Pi Agent Runtime（`AGENT_RUNTIME=pi`）。如需灰度旧实现，才设置
`AGENT_RUNTIME=legacy`；在该模式下把测试账号的平台用户 ID 填入 `AGENT_RUNTIME_PI_USERS`
（逗号分隔），这些账号会继续使用 Pi，其余账号使用旧实现。`AGENT_RUNTIME_FALLBACK=legacy`
时，Pi 在尚未调用业务工具就发生故障时自动回退旧实现；如果 Pi 已经调用工具，则不会重放
旧流程，避免重复改变任务状态。
Pi 只加载平台按当前用户过滤出的业务工具，模型密钥仍由 FastAPI 模型网关管理；切换运行时
不会改变 Skill 发布和执行权限。

网页中的 `/dashboard/workflows` 是工作流 Agent 入口：创建会话后先进入等待日期阶段，Agent
只能请求五类受控动作，页面确认按钮仍调用平台已有状态机。运行任务不再等待管理员审批；
写入型工作流仍保留发起人的写入确认和变更复核。执行失败时，任务卡片直接显示员工、Skill、
失败步骤和原因。

应收核销与其他已发布工具一样默认启用，`FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED` 默认值为 `true`。
用户仍需具备工具权限，并提供有效凭据和业务材料；写前校验、工作副本、回读和幂等规则保持不变。
如需维护暂停，可显式设置 `false`；后端会统一拒绝新的核销执行，已有任务状态仍可读取。
新建配置不再自动关闭核销。启用开关不会自动启动 Worker、创建任务或执行财务写入。

先生成被 Git 忽略且限制 ACL 的 `.env`：

```powershell
D:\BESTEASY\financial_pj\.venv\Scripts\python.exe scripts\prepare_production_env.py
D:\BESTEASY\financial_pj\.venv\Scripts\python.exe scripts\prepare_production_env.py --check
```

随后执行：

```powershell
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml build
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml up -d postgres
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml --profile tools run --rm migrate
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml up -d
```

本机 Caddy 使用内部 CA，自动化检查使用 `curl.exe -k`。当前本机联调配置只绑定
`127.0.0.1`，并只允许 `http://192.168.10.167:18880` 经过出站代理。

## 内网联调模式

只在平台入口保持本机绑定、智云地址位于可信内网且账号为只读账号时使用：

```powershell
D:\BESTEASY\financial_pj\.venv\Scripts\python.exe scripts\prepare_production_env.py `
  --network-mode internal `
  --egress-target http://192.168.10.167:18880 `
  --zhiyun-base-url http://192.168.10.167:18880
```

`internal` 模式拒绝公网 IP、回环地址、链路本地地址、域名、隐式端口和目标列表之外的
IP/端口。Worker 仍只连接内部 Docker 网络，不能直接访问智云；HTTP 请求必须经过代理。
该模式不能与 `0.0.0.0` 等外部监听地址组合。切换目标后必须重新运行 `--check`、Compose
配置校验、镜像构建和精确放行/默认拒绝验证。

## 对外正式部署与智云 FQDN

使用 Caddy 自动申请证书时：

```powershell
D:\BESTEASY\financial_pj\.venv\Scripts\python.exe scripts\prepare_production_env.py `
  --public-origin https://finance.example.com `
  --bind-address 0.0.0.0 `
  --https-port 443 `
  --caddyfile deploy/production/Caddyfile.domain `
  --egress-host zhiyun.example.com `
  --zhiyun-base-url https://zhiyun.example.com
```

使用公司签发的证书时，证书目录必须在 Git 仓库外，且只允许部署账号读取。目录内文件固定命名为
`fullchain.pem` 和 `privkey.pem`，并改用：

```powershell
D:\BESTEASY\financial_pj\.venv\Scripts\python.exe scripts\prepare_production_env.py `
  --public-origin https://finance.example.com `
  --bind-address 0.0.0.0 `
  --https-port 443 `
  --caddyfile deploy/production/Caddyfile.domain-certificate `
  --tls-dir D:/secure/financial-platform-tls `
  --egress-host zhiyun.example.com `
  --zhiyun-base-url https://zhiyun.example.com
```

上述示例域名必须替换为公司正式域名。智云地址只接受 HTTPS、真实 FQDN 和 443，禁止填写
IP、通配符、本机 Hosts 别名或临时反向代理。生成后必须依次运行 `--check`、
`docker compose ... config --quiet` 和现场连通性验收。正式对外部署仍要求真实智云
FQDN；内网联调模式不替代该项验收。无论使用哪种模式，`ar-hexiao-daily` 都不得进入
普通 Pi Skill 目录；真实取数和写入仍需按现有工作流确认与变更复核执行，不再要求管理员审批。

平台正式域名还需要在 Clerk Dashboard 中加入允许来源和重定向地址；平台脚本只更新本地
authorized party 与可信来源，不会代替 Clerk 控制台配置。

运行态验证：

```powershell
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml ps
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml exec -T api python /app/scripts/validate_postgres_runtime.py
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml exec -T api python /app/scripts/run_stage10_pilot.py
docker compose --env-file deploy/production/.env -f deploy/production/compose.yaml exec -T egress-proxy python /app/scripts/egress_proxy.py --check
curl.exe -k -I https://localhost:8443/auth/sign-in
```

创建 PostgreSQL 备份并实际恢复到临时数据库进行逐表哈希比对：

```powershell
.\scripts\backup_postgres.ps1
```

创建两个脏工作树的源码回滚快照时，使用 `scripts/create_source_rollback.py`。快照只收集 Git tracked diff 和未忽略的 untracked 文件；生产 `.env`、凭据密钥及其他忽略文件不会进入归档。

## 登录与任务提醒

功能开关页面及管理接口已移除。平台只使用账号密码登录，不再加载 Clerk 登录组件或接受 Clerk 身份令牌。历史用户绑定字段保留用于数据兼容，不再参与登录。任务提醒默认开启，停用的旧功能开关记录不再覆盖部署配置；提醒仍依赖任务发现 Worker、负责人订阅和有效业务凭据，不会自动创建核销任务。
