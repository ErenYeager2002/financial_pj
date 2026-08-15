# Linux 公网部署

> 本文是早期 Linux/Nginx 部署说明。当前 PostgreSQL、Clerk、Next.js、Caddy、6 个 Worker
> 和精确域名出站代理的受控 Compose 部署以
> `deploy/production/README.md` 为准；不要继续使用本文的 Basic Auth 公网方案承载财务数据。

本目录用于把财务 Skill 平台部署为单机 Linux 服务。推荐拓扑：

```text
Internet
  -> Nginx :443 (HTTPS + Basic Auth)
  -> 127.0.0.1:18000 (FastAPI)
  -> API + 6 个独立 Worker
  -> /var/lib/financial-platform
```

CentOS 7 等宿主机没有 Python 3.11 时，优先使用 `deploy/docker`。该方式将平台
加入现有 `personal-blog_default` Docker 网络，由博客 Nginx 反向代理，但平台的
容器、镜像、配置和数据目录均保持独立。

## Docker 部署

将项目放到 `/srv/financial-platform` 后执行：

```bash
cd /srv/financial-platform
cp deploy/docker/.env.example deploy/docker/.env
mkdir -p deploy/docker/runtime/data
chown -R 10001:10001 deploy/docker/runtime/data
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

API 容器不映射公网端口，只能由共享网络中的 Nginx 访问。Linux 容器使用
Playwright Chromium；本地 Windows 版本仍使用 Edge。

## 前置条件

- 独立域名已经解析到服务器，例如 `finance.eren.xin`。
- Linux 服务器提供 Python 3.11+、systemd、Nginx、OpenSSL 和 Certbot。
- 项目安装到 `/opt/financial-platform`。
- 不上传本机的 `.env`、`data/`、`.venv/`、`.git/` 或任何历史财务文件。

## 安装平台服务

以 root 身份执行：

```bash
cd /opt/financial-platform
bash deploy/install.sh
```

脚本会创建低权限用户 `financial-platform`、Python 虚拟环境、Playwright Chromium、
空数据目录，以及 API 和六个 Worker 的 systemd 服务。API 仅监听
`127.0.0.1:18000`。

## 配置域名、证书和登录保护

先安装 HTTP 引导配置并签发证书：

```bash
mkdir -p /var/www/letsencrypt
sed 's/__DOMAIN__/finance.eren.xin/g' \
  deploy/nginx/bootstrap-http.conf.template \
  >/etc/nginx/conf.d/financial-platform.conf
nginx -t && systemctl reload nginx
certbot certonly --webroot -w /var/www/letsencrypt -d finance.eren.xin
```

创建独立登录口令，切勿复用服务器 root 密码：

```bash
read -rsp "Finance password: " FINANCE_PASSWORD
printf '\n'
printf 'finance:%s\n' "$(openssl passwd -apr1 "$FINANCE_PASSWORD")" \
  >/etc/nginx/.htpasswd-financial-platform
unset FINANCE_PASSWORD
chmod 600 /etc/nginx/.htpasswd-financial-platform
```

启用最终 HTTPS 配置：

```bash
sed 's/__DOMAIN__/finance.eren.xin/g' \
  deploy/nginx/https.conf.template \
  >/etc/nginx/conf.d/financial-platform.conf
nginx -t && systemctl reload nginx
```

## 验收

```bash
systemctl --no-pager --full status financial-platform-api
systemctl --no-pager --full status 'financial-platform-worker@*'
curl -fsS http://127.0.0.1:18000/api/health
curl -I https://finance.eren.xin/
```

公网未带登录信息时必须返回 `401`；登录后首页和 `/api/health` 应返回 `200`。

## 数据和备份

- 运行数据：`/var/lib/financial-platform`
- 环境配置：`/etc/financial-platform/financial-platform.env`
- Nginx 登录文件：`/etc/nginx/.htpasswd-financial-platform`
- 默认 SQLite：`/var/lib/financial-platform/financial.db`

正式使用前至少对数据库、上传文件和工作流目录建立每日备份。平台当前的 Nginx
登录保护适合单用户或小范围内部测试；多人正式使用时应升级为企业统一身份认证。

## 生产环境必填配置

```bash
FINANCIAL_ENV=production
FINANCIAL_SESSION_COOKIE_SECURE=true   # 必须开启，否则启动时拒绝运行
FINANCIAL_SESSION_COOKIE_SAMESITE=lax
# 如有需要，显式声明可信来源（逗号分隔）；默认按请求 Host 推导同源
FINANCIAL_TRUSTED_ORIGINS=https://finance.example.com
```

- 平台内置会话 Cookie 认证；生产部署必须在 HTTPS 之后，并把
  `FINANCIAL_SESSION_COOKIE_SECURE=true` 写入环境配置，否则进程拒绝启动。
- `/docs`、`/redoc`、`/openapi.json` 现在需要登录后才能访问，只有 `/api/health` 匿名。
- 状态变更请求（POST/PUT/PATCH/DELETE）会校验 `Origin`/`Referer` 同源；跨来源请求被拒绝。
- 数据库采用版本化迁移（Alembic）：启动时先 stamp 历史库到基线，再升级到 head，
  会真实执行认证等后续迁移。迁移前请用 `scripts/backup_database.ps1` 备份。
- 默认备份不含 `data/credential.key`（模型连接与业务凭据的加密密钥），
  恢复备份后这些凭据无法解密；如需凭据恢复能力，使用 `--include-keys` 并把
  `credential-recovery/` 目录与主备份分开、限制 ACL 单独保管。

## 安全禁令（P0-01）

在服务端用户登录鉴权、审批和写入型任务硬闸完成并验收之前：

- **禁止**用公网隧道（frp / ngrok / Cloudflare Tunnel / ssh -R 等）把平台端口
  或真实财务文件暴露到公网；
- **禁止**创建共享匿名账号或 `public-gateway-user` 之类的公网入口；
- 未登录时 Nginx 必须返回 `401`，任何目录都不允许匿名访问；
- 部署后必须确认 `.env` 与 `data/` 未包含公网可访问的历史财务文件。
