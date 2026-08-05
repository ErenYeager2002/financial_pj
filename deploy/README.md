# Linux 公网部署

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
