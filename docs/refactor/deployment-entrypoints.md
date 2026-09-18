# 部署入口证据

2026-09-18 只读采集。源码存在、文本引用、运行启用及业务调用证据分别记录；未发现运行证据不构成删除授权。引用采用文件名匹配，属于候选，可能同名误匹配。

| 路径 | 代码存在 | 配置引用候选 | 实际启用 | 调用证据 |
| --- | --- | --- | --- | --- |
| agent-runtime/Dockerfile | 是 | deploy/development/compose.yaml, deploy/production/compose.yaml, scripts/dev.ps1, web/Dockerfile.monorepo, web/Dockerfile.rebuild | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/development/compose.lan.yaml | 是 | scripts/dev.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/development/compose.yaml | 是 | scripts/backup_postgres.ps1, scripts/dev-stop.ps1, scripts/dev.ps1, scripts/start.ps1, scripts/stop.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile | 是 | deploy/development/compose.yaml, deploy/production/compose.yaml, scripts/dev.ps1, web/Dockerfile.monorepo, web/Dockerfile.rebuild | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile.crossday-20260916 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile.current-material | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile.empty-day | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile.history-rebind | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile.material-hide | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile.material-selector | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/docker/Dockerfile.report-empty | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/production/compose.yaml | 是 | scripts/backup_postgres.ps1, scripts/dev-stop.ps1, scripts/dev.ps1, scripts/start.ps1, scripts/stop.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/systemd/financial-platform-api.service | 是 | deploy/systemd/financial-platform-worker@.service | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deploy/systemd/financial-platform-worker@.service | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.ar-evidence-api | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.ar-evidence-worker | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.flow-order-only-20260917 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.native-sandbox | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-activity | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-agent | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-api | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-bridge | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-browser | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-business | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-business-runtime | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-chat-jobs | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-context | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-context-api | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-dialogs | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-egress | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-files | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-jobs | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-model | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-model-egress | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-model-runtime | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-skills | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-tools | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/Dockerfile.pi-web | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| deployment/compose.pi-runtime.yaml | 是 | 未发现 | 已确认部署副本启动 model-broker 与 egress；未证明与此分支文件哈希相同 | 尚未采集业务调用追踪 |
| deployment/financial-native-sandbox.service | 是 | 未发现 | 同名 systemd 服务 active/running；文件哈希仍待比对 | 尚未采集业务调用追踪 |
| deployment/financial-pi-runtime.service | 是 | 未发现 | 同名 systemd 服务 active/running；文件哈希仍待比对 | 尚未采集业务调用追踪 |
| scripts/backup_database.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/backup_postgres.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/bootstrap.ps1 | 是 | scripts/backup_database.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/build-dev-launcher.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/convert_receivables_pivot.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/dev-frontend-host.ps1 | 是 | scripts/dev-frontend-hot.ps1, scripts/dev-stop.ps1, scripts/dev.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/dev-frontend-hot.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/dev-stop.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/dev.ps1 | 是 | deploy/development/compose.lan.yaml, scripts/dev-frontend-hot.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/enable_lan_access.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/start-frontend-prod.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/start.ps1 | 是 | scripts/bootstrap.ps1, scripts/sync_from_gitee.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/stop.ps1 | 是 | scripts/sync_from_gitee.ps1 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| scripts/sync_from_gitee.ps1 | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| web/Dockerfile.material-selector | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| web/Dockerfile.monorepo | 是 | deploy/production/compose.yaml | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| web/Dockerfile.pilot | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |
| web/Dockerfile.rebuild | 是 | 未发现 | 尚未确认此文件的运行版本 | 尚未采集业务调用追踪 |

## 真实部署与仓库配置的差异

主应用容器由部署根 compose.yaml 启动；它不等于仓库 deploy/production/compose.yaml，后续完整重建必须核实并纳入正式发布配置。当前 API、Next、standard/discovery/agent Worker、gateway、postgres 和 egress-proxy 都处于 running。不能凭仓库 Compose 推断全部线上服务。

Pi model-broker 与 egress 的 Compose 标签指向当前发布源码中的 deployment/compose.pi-runtime.yaml。另有 3 个独立 Pi 会话容器，未记录用户或会话标识。financial-native-sandbox.service 和 financial-pi-runtime.service 在 systemd 中 active/running。

未检查系统计划任务和各 systemd ExecStart 对应源码哈希；PR-00 部署盘点仍未完成。
