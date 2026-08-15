# 阶段十本机容器部署

该拓扑把 Next.js、FastAPI、PostgreSQL、6 个 Worker、精确目标出站代理和 HTTPS 网关放入独立 Compose 项目：

- 唯一主机入口是 `https://localhost:8443`；
- PostgreSQL、FastAPI、Next.js 和 Worker 均不映射主机端口；
- 运行时 Skill 使用独立 `skill-data` 持久卷；API 可原子发布，Worker 只读挂载；
- Worker 只加入 `internal` 数据网络，不能直接访问公网；需要联网的 Skill 子进程只能通过出站代理；
- 出站代理的 `strict` 模式只接受 HTTPS CONNECT，并按精确 FQDN 和 443 端口放行；`internal` 模式只允许显式配置的 RFC1918 IPv4、HTTP 协议和端口；空目标列表默认拒绝全部目标；
- FastAPI 和 Next.js 可访问外部 Clerk，浏览器只访问同一 HTTPS 入口；
- `ar-hexiao-daily` 在真实取数、受控写入专项回归和管理员批准完成前继续保持 disabled。

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
FQDN；内网联调模式不替代该项验收。无论使用哪种模式，`ar-hexiao-daily` 都必须在
受控写入专项回归和管理员批准前保持 disabled。

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
