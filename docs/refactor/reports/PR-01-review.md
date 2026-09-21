# PR-01 首轮双轴审查

固定点 6fce5bf1195c0591d8f8cfb53b84c32c0356f36d，审查包含其后未提交差异和新增文件；规格为 execution-guide.md §6.3。两位独立审查者只读检查，未运行生产操作。

## Standards

1. P1：CLI 忽略 PGHOSTADDR，可通过 libpq 环境地址绕过可见 host 目标校验。现已同时拒绝 PGHOSTADDR 和未显式 URL 端口时可能生效的 PGPORT，并添加“创建 Engine 前拒绝”回归。
2. P2：兼容策略接受 f1，但未核验旧 SQLite 缺失运行列。现已只读检查 15 个必需运行字段，f1/f2 缺列均拒绝，不自动补列。
3. 判断项：初始密码文件发布后 DB commit 失败会留下不对应已提交账号的受限文件。已记录恢复规则，但相反顺序的提交失败专项尚需补充。

## Spec

1. 实际部署门禁未接线：根 Compose 与仓库模板不同，PlatformAdapter.cutover 使用 up --no-deps，跳过依赖。必须显式迁移后再切换并验证失败不启动新服务。
2. 同上，f1 SQLite 缺运行列会错误 ready；此次新增检查与测试已修复。
3. 规格要求多迁移进程竞争和多 Worker 启动。现有锁竞争、并发检查不是完整入口证据，需补命令/进程级专项。

离线条款要求保留 online/offline 且离线不连接生产库，没有明确要求重写所有已发布历史数据迁移。本次 e0→f2 PostgreSQL 离线 SQL 生成和执行验证可证明当前增量路径；历史完整链/SQLite 条件修复的限制继续明确记录，不宣称支持。

两轴首轮各指出上述问题，不视为 PR-01 通过。修复后 migrate 34 项、schema-check 20 项通过；实际部署入口和入口级竞争验证尚待完成。

后续补证：两个真实迁移 CLI 进程互斥并重查版本，三个真实 Worker 单轮进程在拒绝 DDL 的 authorizer 下启动通过；迁移 35 项、schema-check 21 项通过。此证据限定合成 SQLite，实际部署入口缺口仍未关闭。


### 候选镜像后的第二次发布审查

两路只读审查确认仍有上线阻塞：

1. maintenance_flow 在最后一次 wait_idle 后才切 full，随后开始迁移及 force-recreate；普通 Worker 和 discovery Worker 不读取维护模式，采样不构成关闭新执行的屏障。必须先关闭新请求入口，并保证后台调度不再启动新执行，再排空并确认；不得强行中断在途财务任务。
2. 普通 backend-schema 的历史成功复用只核对容器 exit0 和发布身份，尚未像 recover-schema 一样回读当前 DB。数据库恢复后历史执行结果可能过期。所有复用路径必须验证当前目标 revision、兼容结构和 seed，否则拒绝切换。

已核实候选镜像本身的隔离 PostgreSQL f1→f2、重复迁移、seed 唯一和无 DDL 角色运行检查通过，不能据此代替发布编排保护。禁止在上述两项未解决前上线。


### 统一发布前当前库核验

platform_adapter.verify_schema_target 使用候选镜像的 check_runtime_database，通过独立只读 PostgreSQL 进程核验受支持版本、必需表列和 global seed，并严格比对目标 revision。新迁移与历史复用两条路径均在发布 Compose 前执行；失败只停止切换，不自动重跑迁移。现有 recover-schema 的版本预检保留，正式切换前同样经过完整核验。

schema-release 17 项通过，包括数据库恢复旧备份后的历史成功记录不能绕过核验、失败时不发布配置或启动服务。此为命令替身验证；候选镜像自身数据库检查已通过前述隔离 PostgreSQL 测试。本轮未连接业务库执行新探针、未停止线上服务。审查项“任务排空与新执行之间缺乏屏障”仍未关闭，尚不允许上线。


### Schema 发布任务排空与平稳退出

新增 quiesce_schema_services：要求 full 模式并实际探测公开应用路径返回 503；等待空闲，平稳停止 discovery Worker，再次排空其最后一次检查产生的任务，然后平稳停止 standard Worker 和 API，最终只读活动计数必须全部为零才允许迁移。活动计数新增 assistant_turns running，避免仅财务任务为空时中断正在进行的对话。

stop_schema_service_gracefully 只允许三个 schema 服务，核对容器 Compose 身份及前后容器 ID，使用 docker stop --timeout -1 禁止超时强杀，要求实际 exited 且 exit_code=0。观察超时保持维护并拒绝迁移，不能把超时视为退出。发现非零剩余任务不自动重跑。其他发布计划未改变。

schema-release 19 项通过。另在禁网、只读、临时容器中使用候选镜像实际 worker.run_loop 信号处理，替换 run_once 为 4 秒合成任务：SIGTERM 后任务完成、循环停止、容器 exit0；未执行真实核销。首个合成探针因测试替身修改 frozen settings 失败，修正测试替身后通过，失败容器已按专用标签清理。这不是生产任务演练，仍需复核平稳停止失败后的恢复和回滚路径。线上未停止或重建任何服务，未触碰看板。


### 首次真实发布与兼容回退（2026-09-18）

第三轮复核恢复入口后，schema-release 30 项通过；候选与回滚镜像对线上 f1 的只读检查通过。正式执行 backend-schema：零活动任务、维护排空、迁移成功退出，DB 更新到 f2a3b4c5d6e7，三个目标服务曾切到候选 1a051c67b34d。稳定门禁发现受保护的财务 worker-agent 在 API 不可用期间自行重启（Docker events），触发自动回退；三个目标服务成功运行兼容镜像 e314f8d13e01。旧 protected StartedAt 基线已经变化，当前发布观察不可能自行通过；核实迁移 exit0、回滚容器均运行且观察进程无子命令后，仅 SIGINT 结束该发布观察进程，未终止业务 Worker 或任务。原发布退出130，证据见 PR-01-deployment.json。

随后独立 recover --apply 重新完成稳定健康检查并恢复 normal（exit0），详见 PR-01-access-recovery.json。最终回读：normal、DB f2、三个服务均为兼容回滚镜像、Agent 原镜像仍运行、公开 session API 401（未登录的正常响应）。证据 PR-01-runtime-after-rollback.json。发布未验收通过，不能标 PR-01 完成。

源码核实 Agent main 的 claim 请求异常直接落入顶层 catch 并 exitCode=1；退出日志不输出具体异常，因此 API 停机导致重启的判断基于生命周期事件与调用路径，不虚构不存在的错误日志。下一步需把空闲 Agent 的停启纳入 API 维护依赖保护，避免用 claim 自动重试掩盖可能已领取任务的状态不确定性。仅财务平台资源发生变更，看板无操作。
