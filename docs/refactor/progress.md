# 改造进度

用户明确限制：不得修改、重启、部署或清理同机看板平台的任何代码、配置、服务、容器和数据；不得调整可能影响看板的共享主机配置。后续所有操作严格限定财务平台及本次独立测试资源。

分支：refactor/full-platform-20260918。基线：2cd58e91348ff566250f03b882f22c46425bbe1f；当前提交：6fce5bf1195c0591d8f8cfb53b84c32c0356f36d；此后仍有未提交修改。远程工作树为 refactor-worktrees/full-platform-20260918，与生产发布目录分离。

| 阶段 | 状态 | 依据 |
| --- | --- | --- |
| PR-00 | 基线阶段完成 | reports/PR-00.md 与双轴审查；失败和未知项明确保留 |
| PR-01 | 已上线，阶段验收整理中 | reports/PR-01-runtime-verified.json；第二次发布 exit0，normal、DB f2、三个服务源码哈希一致 |
| PR-02 | 本阶段事务范围已验收并上线 | reports/PR-02.md、PR-03-attempt-audit-runtime-verified.json |
| PR-03 | 前后端与历史回填已上线，阶段验收整理中 | PR-03-runtime-verified.json、PR-03-native-backfill-verified.json、PR-03-web-runtime-verified.json；最终阶段验收未完成 |
| PR-04 | 普通任务授权部分已上线，其余入口继续实施 | reports/PR-04.md、PR-04-runtime-verified.json |
| PR-05 | 进行中，Workflow/Pi代次校验已上线 | reports/PR-05-pi-runtime-verified.json；统一重试政策、终态及故障矩阵未完成 |
| PR-06 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-07 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-08 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-09 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-10 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-11 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-12 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-13 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-14 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-15 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-16 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-17 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-18 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-19 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-20 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |
| PR-21 | 未开始 | 按 execution-guide.md 的依赖和验收执行 |

## 当前证据

2026-09-20：管理员Workflow停止的实际锁等待身份变更6项补充通过，总232项专项通过；仅测试/文档，无服务切换。下一项按PR-04-execution-snapshot-scope.md落实完整执行快照（原始消息当前未纳入input_hash）及可信历史恢复；其余PR04矩阵和后续阶段保持未完成。

2026-09-20 07:39 UTC，停用账号Workflow管理员受审计停止已上线34623fa49afc，受限恢复2f6c56d41385。226项专项、契约生成/检查、候选/恢复隔离检查通过，三后端各199+236哈希一致，新增两管理接口真实匿名HTTP401、normal。保留另一会话71734的12个AR变动。见reports/PR-04-workflow-admin-stop.md。下一项继续完整阶段授权观察/确认快照矩阵；完整目标未完成。

2026-09-20：Worker取数确认外层事务补充验收通过，207项专项全绿；新增4项真实execute_workflow_action普通/空日提交与回滚场景。仅测试/文档变更，无服务重启。下一项停用账号Workflow管理员受审计停止；完整目标未完成。见reports/PR-04-worker-confirmation-transaction-tests.json与PR-04-disabled-owner-workflow-scope.md。

2026-09-20 07:20 UTC，取数确认实际身份、同事务审计与 Pi 租约复核已上线 ac2d432cf582，受限恢复 4754098e38db。203项专项与候选/恢复隔离检查通过，三后端各199+232文件哈希一致，normal。保留另一会话6781115382e8的14个AR变动。见reports/PR-04-fetched-confirmation.md。完整Worker外层回滚验收、PR04剩余矩阵及后续阶段仍未完成。

2026-09-20 06:50 UTC，单日/批次补取实际actor、锁后状态与同事务审计已上线6940bdbe8edb，受限恢复4fe7e5210e03。180项专项、双轴审查和候选/恢复检查通过；三后端各199+228文件哈希一致，UID10001、restart0、DB f3、normal、活动零。另一会话76753d003312的35个AR改动已通过内容比对合并并完整保留，见PR-04-supplement-business-base.json。详见reports/PR-04-supplement-boundary.md及runtime-verified.json。下一步人工/自动取数确认及审计事务，完整目标未完成。

2026-09-20 06:39 UTC，重置入口当前actor/状态及同事务审计已上线0a59d4d46913，受限恢复998a5d888924。165项专项、双轴审查及候选/恢复镜像检查通过；三后端各199+213文件哈希一致，UID10001、restart0、DB f3、normal、活动零。见reports/PR-04-reset-boundary.md及runtime-verified.json。取数确认/补取调用与审计事务缺口已记录在PR-04-material-entry-audit.md，待继续实施；完整目标仍未完成。

2026-09-20 06:31 UTC，聊天模型决策前后身份/任务绑定和事务分段已上线5d2fd766b857，受限恢复c3685cabe006。156项专项通过，包含确认日期和确认写入、模型期间无事务/可获得调度锁。双轴审查与镜像检查通过。三个后端各199+213文件哈希一致，UID10001、restart0、DB f3、normal、活动零。见reports/PR-04-chat-boundary.md及runtime-verified.json。下一步材料确认/补取/重置入口实际actor与完整阶段矩阵；整体目标未完成。

2026-09-20 06:20 UTC，PR-04 直接 Agent 当前操作者与阶段检查已上线 8936841ccc9a，受限恢复 ced5b1c92931。137 项专项及 Agent 接口兼容测试、双轴审查、候选/恢复镜像检查通过。三个后端服务各 199+213 文件哈希一致，UID10001、restart0、DB f3、normal、活动零。见 reports/PR-04-agent-actor.md 与 runtime-verified.json。剩余边界清单见 reports/PR-04-boundary-gaps.md，下一步核查聊天模型决策前后边界。完整目标仍未完成。

2026-09-20 06:11 UTC，PR-04 恢复实际操作者校验已上线 0a0c0d2b6127，受限恢复镜像 8b80ae47e940。121 项授权专项、双轴审查、候选/恢复镜像隔离检查通过；三个服务各 199 后端与 213 AR 文件哈希一致，UID10001、restart0、DB f3、normal、活动计数零。见 reports/PR-04-recovery-actor.md 与对应 runtime-verified.json。此前记录为历史证据，完整目标仍未完成。

2026-09-20 06:03 UTC，PR-04 Workflow 取消身份/状态刷新已上线 c486d105bc74；111 项授权专项通过。已保留另一会话 c24e96ed5c8a 新增 12 个 Skill 文件，三个后端服务各 199 个后端及 213 个 AR 文件哈希一致，normal、restart0、DB f3，活动任务零。完整证据见 reports/PR-04-cancellation.md 与 runtime-verified.json；恢复镜像 81b52a8d4310。下方此前发布结果为历史记录，PR-04 全阶段验收及 PR-05 至 PR-21 仍未完成。

2026-09-20 05:42 UTC，PR-04普通任务提交摘要在确认/执行阶段的再次校验已上线：镜像d60f2a7c0063，三个后端服务各199个后端文件与209个最新AR包文件哈希匹配，UID10001、restart0，DB唯一revision=f3a4b5c6d7e8，submission_replay_only=false，mode/public normal，五类活动任务0。证据PR-04-input-digest-deployment.json与runtime-verified.json。85项专项、4项普通E2E和5项草稿提交通过。恢复镜像10c5c232fe72保留授权/确认/快照检查与最新AR业务更新，只允许已绑定回执重放。

用户明确要求保留另一会话核销更新：已继承ar-flow-completion-20260920（c16bec8cca87），209个AR包文件完整保留，新增10项授权源码已合并持久化工作树，记录PR-04-input-digest-business-base.json。未提交推送、未执行真实核销/自动重试，看板未操作，前端无本轮构建重启。

PR-04全路径阶段矩阵与完整确认内容绑定仍未完成（现有摘要不含原始message）；PR-01至PR-03仍有阶段验收项，PR-05至PR-21未开始，完整G01–G16/T01–T90/I01–I30范围保持。历史基线失败未宣称清零。

## 下一安全任务

进行浏览器及PR-01至PR-03逐项验收；正式前端镜像构建、隔离运行探针和第二次安全切换已完成。当前线上基准是f3与PR-03-runtime-verified.json；不得再次从f2执行升级。PR-04普通任务授权已上线；Pi现有会话停止/取消及Skill发布身份边界已上线；Native安装授权亦已上线；管理员代停后台接口已上线；继续补齐Workflow/AR各阶段授权观察、审批与写入资格矩阵。

## 历史实施记录

以下保留当时的阶段状态，线上当前状态以上面的回读结果为准。

PR-01 首步已完成：Alembic 复用外部连接及 offline URL 支持，新增 3 项回归通过（修改前 2 项失败）。其余迁移锁、schema/seed、legacy、部署和验证待完成，详见 reports/PR-01.md。

PR-01 新增只读 schema 兼容检查，11 项隔离测试通过。支持显式多个兼容 revision，不隐式建表/升级；尚待迁移锁、幂等 seed、正式 revision、运行入口替换与 PostgreSQL 无 DDL 角色验证。

PR-01 迁移锁首版已加入；SQLite 跨进程竞争/超时、异常释放、保留锁 inode、调用方事务拒绝及符号链接保护相关 4 项测试通过。PostgreSQL advisory lock 分支尚未实际验证，不视为迁移互斥验收通过。

PostgreSQL advisory lock 与只读无 DDL 角色专项 3 项已在独立测试数据库通过，清理退出 0。下一步统一迁移命令与幂等 seed，保持看板全部资源及生产财务数据库不变。

统一迁移用例及幂等 seed 已实现；SQLite 6 项、PostgreSQL 专项含完整现有迁移链共 4 项通过。正式缺表/补列 revision、legacy 导入、CLI 和服务切换待完成。

PR-01 新 revision f1a2b3c4d5e6 补齐 assistant_turns；SQLite 迁移 9 项、PG 4 项、Native 产物 1 项通过。历史基线缺表已在重构工作树修复，生产尚未迁移。

已有 PostgreSQL assistant_turns 时间字段现校验时区；兼容表数据保留、不兼容表拒绝升级的专项通过，PG 迁移测试共 6 项通过。PR-01 仍需运行入口接线、legacy 升级及部署验证。

API/标准 Worker/发现 Worker 的改造分支启动入口已接入只读检查；schema-check 18 项通过。统一迁移 wrapper、受控 legacy 升级、CLI 和部署依赖尚待完成，暂不发布半成品启动链。

显式 schema 迁移 CLI 已加入，迁移专项 22 项、PG 专项 6 项通过；目标与版本需明确传入，URL/环境覆盖受到限制，错误不泄露连接凭据。尚需旧 SQLite/legacy、init_db wrapper、Compose/prestart 接线和上线验证。

旧 SQLite 的 15 列补丁已进入正式 revision f2a3b4c5d6e7，旧运行补列函数移除。迁移 24 项、schema-check 18 项、PG 6 项及两条产物/E2E 验证通过。无版本 legacy 验证、旧库约束补齐、离线链和部署接线仍未完成。

init_db 已收敛为只读 wrapper；18 个测试文件显式迁移准备，两个维护入口也改为只读检查。E2E/Native/取数包共 23 项通过；生命周期组 13 通过、2 个已确认存在于 PR-00 的工作流领取失败仍保留。受控 legacy 导入和部署接线未完成。

显式 legacy 接管已实现严格基线结构验证与同连接事务，迁移专项 32 项、PG 6 项通过；升级中部分 DDL 失败回滚已验证。生产未接管/迁移。PR-01 仍需 bootstrap 幂等、离线链、部署接线及最终审查。

管理员初始化已独立串行化并使用 0600 原子密码文件发布；SQLite 专项 4 项、PG 专项 7 项、普通 E2E 1 项通过。生产账号和凭据未变更。离线链及部署接线仍待完成。

生产/开发 Compose 模板已设置迁移成功门槛，并将一次性 SQLite 数据导入分离到显式 profile。4 项回归及两套合成配置解析通过；当前生产根 Compose 未替换，服务未重启，仍需实际部署入口适配与最终验证。

当前版本区间的 PostgreSQL 离线 SQL 已禁止连接生成并实际执行验证；migration-connection 4 项、PG 8 项通过。历史全链离线在 e91b7c4a2d30 反射检查失败，另有两处数据相关 Python 回填，保持未完成状态。

首轮双轴审查已完成并修复两个安全/正确性问题：PGHOSTADDR/PGPORT 目标覆盖、f1/f2 缺运行列误判 ready。迁移 34 项、schema-check 20 项通过。实际发布使用硬编码 API 镜像与 --no-deps，已确认需显式适配；模板门禁不能算线上接线完成。

入口级并发已补：两个真实迁移 CLI 互斥并重查版本，三个真实 Worker 同时启动且无 DDL 尝试；migrate 35 项、schema-check 21 项通过。仍待实际发布门禁适配和上线验证。

实际托管发布已新增 backend-schema 方案，显式迁移成功后再更新三个财务服务镜像和切换；6 项失败门禁/配置保护测试及真实 Compose 内存转换通过。尚未执行发布，仍需超时跟踪、恢复与线上前置核验。

发布迁移增加固定容器句柄和持久状态，超时后只查询不重跑；运行/失败/未知状态均阻止切换与恢复。schema-release 9 项测试通过；生产尚未执行，仍需失败恢复、归档清理和实际上线核验。

- PR-01：补充 bootstrap 提交前失败回滚与提交后报错两种恢复验证，隔离套件 6 项通过；线上未变更，发布恢复工作继续。

- PR-01：超时后按原容器状态及完整发布身份复用已成功迁移，禁止运行中重跑；schema-release 11 项通过。线上只读确认当前 revision=f1a2b3c4d5e6，四类活动计数为 0；尚未部署。

- PR-01：新增 recover-schema 显式恢复，核对当前 DB revision 与原发布身份；按迁移容器名保存受限权限历史记录。schema-release 14 项通过，三个入口语法及静态 diff 通过；尚未上线。

- PR-01：构建候选镜像 1a051c67b34d，修复基础镜像遗留同 revision 文件导致双 head 的实际构建问题；47 个源码哈希、运行 UID/GID、唯一 head、镜像内新 SQLite 迁移与运行只读检查通过。未切换线上。

- PR-01：实际候选镜像隔离 PostgreSQL 验证及只读发布预检通过；二次审查发现发布任务排空窗口、普通迁移复用缺少当前库核验，两项修正前不执行上线。

- PR-01：普通与恢复发布统一增加候选镜像当前库只读核验，修正历史成功结果复用缺口；17 项发布测试通过。任务排空屏障仍待实施，未上线。

- PR-01：增加 full 入口关闭确认、两次排空、三服务无强杀平稳停止及最终零任务门禁，含进行中助手对话。19 项测试及真实 Worker 信号处理合成探针通过；尚待恢复路径复核，未上线。

- PR-01：发现原镜像不识别升级后 revision，已构建兼容回滚镜像 e314f8d13e01；139 个原业务源码哈希不变，隔离 PostgreSQL 验证通过。待接入明确恢复/回退路径，未上线。

- PR-01：接入迁移前原容器全部干净退出时的恢复分支，须配置/DB版本/容器身份一致且恢复健康通过；23 项针对性测试通过。升级后兼容回滚与部分停止恢复仍待完成，未上线。

- PR-01：部分停止恢复和升级后兼容应用回退已接入，backend-schema 必须提供精确回滚镜像；27 项针对性测试通过，未上线。

- PR-01 真实发布未通过稳定门禁：DB 已成功到 f2，应用自动回退到兼容镜像 e314f8d13e01；独立恢复检查通过并恢复 normal。Agent 因 API 停机自行重启，需完善维护依赖后再发布，PR-01 未完成。

- PR-01：新增 Agent 原容器在 API 维护前后平稳停启及身份保护，32 项测试和原 Agent 镜像空闲 SIGTERM 探针通过；待复核后再发布，当前 normal/兼容回滚镜像。

- PR-01：Agent 协调停止标记改为0600原子持久化，跨进程恢复验证通过，发布专项33项通过；线上仍正常运行兼容回滚版本，等待本轮复核后切换。

## 2026-09-20 当前后端发布

PR-03 backend-schema 发布退出0，平台normal；API、标准Worker、发现Worker的新镜像和源码哈希一致，DB=f3a4b5c6d7e8，submission_replay_only=false，receipt查询契约存在。Agent保留原镜像，部署后均无重启循环。受限恢复镜像已经构建并验证，本次未触发回退。

前端隔离生产构建通过，但正式前端镜像尚未发布；Native历史身份分批回填、浏览器验收、PR-01至PR-03完整阶段验收仍未完成。下一步不得再按旧f2升级；源码与线上基准使用PR-03-runtime-verified.json。PR-04至PR-21尚未开始，目标范围不变。未执行真实核销、未自动重跑失败任务，未提交或推送，看板无操作。

## 旧发布证据归档

### PR-01发布时的记录

2026-09-18 09:57 UTC，PR-01 第二次发布成功，平台 normal。API、标准 Worker、自动检查 Worker 均运行候选镜像 1a051c67b34d，每个容器 47 个源码哈希匹配；数据库唯一 revision 为 f2a3b4c5d6e7。Agent 使用原容器和原镜像，经协调停启后运行，身份及启动状态与持久记录相符。五类活动任务为零，公开会话接口返回正常未登录状态 401，健康验证通过。运行证据：reports/PR-01-runtime-verified.json，部署证据：reports/PR-01-deployment-second.json。

发布专项 33 项通过；新旧 SQLite、PostgreSQL、迁移锁、真实 CLI/Worker 并发及无 DDL 角色验证见 reports/PR-01.md。首次发布触发 Agent 自行重启保护并应用兼容回退，已保留失败及恢复证据，不以第二次成功覆盖首次失败记录。未执行真实核销或自动重跑财务任务；看板平台无操作。

后端全量测试、格式/lint、OpenAPI 和前端部分基线失败仍见 baseline-failures.md，未宣称全部清零；GitHub CI 未执行本轮未提交配置。文件保留 cron 的已知问题仍未修复或补跑删除。G01–G16、T01–T90、I01–I30 及 PR-02 至 PR-21 的最终验收尚未完成，完整目标范围不变。

PR-04 普通工具固定输入检查已上线：提交哈希、当前记录、源文件及复制后的字节一致；刷新身份、固定部门并保留管理员同部门规则。专项60项、普通E2E4项及候选/恢复镜像验证通过。下一步普通确认记录和Skill快照启动检查、全路径授权矩阵仍未完成。详见reports/PR-04-input-binding.md。

## 本轮开始时的发布状态（历史）


2026-09-20 05:17 UTC发现并行发布：线上后端变为ccf155fe9ee6（ar-allocation-contract-20260920），其backend app与上一轮输入检查版本一致，仅AR Skill相关10文件更新；当时mode=full。本轮普通确认检查70项专项+4项E2E通过，但发布预检失败且没有apply，未在线上生效。用户已确认保留并合并另一会话的更新；10项Skill已同步远程源码。PR-04-image.json现为基于ccf155fe9ee6的合并候选e8ea15dac0ad，恢复镜像2cb757b77426；二者10项Skill哈希均保留且隔离检查通过。线上仍full，尚未apply；不能当作当前线上。待并行发布恢复normal再预检切换，见reports/PR-04-confirmation.md。

2026-09-20 后端 PR-04 普通任务授权部分已发布：API、标准 Worker、发现 Worker 均为镜像 6bc600a791f2，各197个后端源码哈希匹配，DB唯一revision=f3a4b5c6d7e8，submission_replay_only=false，平台normal，五类活动任务为0。证据见reports/PR-04-input-binding-deployment.json及PR-04-input-binding-runtime-verified.json。PR-04全部阶段授权尚未完成。

295条Native历史记录已按100条一页分三批补充会话与命令身份，零异常；原字段摘要前后一致，再次只读检查processed=0、skipped=295。证据见reports/PR-03-native-backfill-preview.json、PR-03-native-backfill-applied.json、PR-03-native-backfill-verified.json。没有执行真实核销、没有自动重跑财务任务，看板未操作。

前端第二次发布已通过运行回读：镜像882434f388fd与源摘要匹配，登录页200，未登录回执接口401，平台normal。第一次发布因Compose固定旧镜像误报成功，已保留失败记录并修复发布门禁；37项发布验证通过。PR-02本阶段验收已整理；PR-01历史全链离线迁移、PR-03真实浏览器验收及PR-04至PR-21仍未完成。全量基线失败继续见baseline-failures.md，未宣称全部清零。G01–G16、T01–T90、I01–I30和全部PR阶段的完整目标范围不变。

## 输入摘要修复前的运行状态（历史）


2026-09-20 05:31 UTC，PR-04普通确认必要条件和固定Skill快照检查已合并上线：镜像eb9577118d16，三个后端服务各198个后端源码和205个AR包文件哈希匹配，UID10001，DB唯一revision=f3a4b5c6d7e8，submission_replay_only=false，restart0，mode/public normal，五类活动计数0。证据PR-04-snapshot-deployment.json、PR-04-snapshot-runtime-verified.json。专项77项、ordinary-e2e4项通过；当前恢复镜像a23938055ebd保留安全检查和AR更新，仅允许已绑定提交回执重放。

用户授权保留另一会话应收核销更新：以其最终d48bf2b825bc构建，正式/实验Skill共205项文件保持一致；10项新增业务修改已合并远程持久化源码，记录PR-04-confirmation-ar-merge.json。未提交推送，未执行真实核销或自动重试，看板未操作。

PR-04完整确认载荷绑定及Workflow/AR/Agent全阶段矩阵尚未完成；PR-01至PR-03仍有阶段验收未完成项，PR-05至PR-21尚未开始。G01–G16、T01–T90、I01–I30和完整阶段范围不变。前端保持上一部署，无本轮重启；历史基线失败未宣称清零。


2026-09-20 08:07 UTC，PR-04 普通执行意图快照已部署：f339be44cc66，数据库唯一版本 f4b5c6d7e8f9，三个后端各 442 项哈希匹配（202 项后端、240 项正式/实验 AR 文件），UID10001/restart0/replay_only=false，平台 normal。255 项专项、4 项普通端到端、5 项草稿、10 项提交编排通过，候选/恢复迁移验证通过。保留另一会话 f86f4d4c8e87 的 16 项变更；恢复镜像 3a7aeb8d1967 支持 f4 且限制新普通提交。正式证据见 reports/PR-04-execution-snapshot.md 与 runtime-verified.json。PR-04 全矩阵仍未完成，PR-05～PR-21 尚未开始。


2026-09-20 08:20 UTC：PR-04 审批管理员当前身份/并发决定切片已上线，镜像 a2058278611f，恢复镜像 d377c35a736b。24 项 PostgreSQL 专项通过；三个后端各 442 项文件哈希匹配，DB f4、UID10001、restart0、replay_only=false，平台 normal；审批两个匿名入口实测401。另一会话 240 项 AR Skill 文件完整保留。详见 reports/PR-04-approval-authorization.md 和 runtime-verified.json。PR-04 整体未完成，PR-05～PR-21 尚未开始，无真实核销/财务写入、无看板操作。


2026-09-20：补充 PR-04 真实调用链核对。审批申请/执行审批helper当前无生产调用；普通取消不会将已发布待登记任务改为cancelling。新增4项真实取消service的PG回归，连同审批套件28项通过，证明原完成动作保留和剩余日期停止；不证明真实登记或撤权后的完成授权。仅测试及正式核对文档变更，无生产代码或服务更新。下一缺口与证据见 reports/PR-04-phase-boundary-audit.md。


2026-09-20 08:34 UTC：已发布依据当前登记核验切片已上线，镜像0d1a589a0110，恢复镜像518da2aa608b；39项专项通过。三个后端各442项哈希一致、UID10001/restart0/DB f4/replay_only=false，平台normal。240项AR文件保持不变。只解决发布回读的陈旧材料/成员/文件登记问题，没有放宽撤权检查；受限系统收尾与阶段授权审计仍未完成。证据见reports/PR-04-publication-current-evidence.md及runtime-verified.json。


2026-09-20 08:43 UTC：正式辅助台账登记前共享校验及复制后指纹核对已上线，镜像6080fb032ae1，恢复745e65216a9d。48项相关PG测试通过；三个后端各444项哈希一致、UID10001/restart0/DB f4/replay_only=false，平台normal。保留另一会话3633767a15fd的10项更新及全部242项AR文件。撤权权限检查未放宽，PR-04全阶段观察/受限收尾仍未完成。证据见reports/PR-04-formal-ledger-registration.md及runtime-verified.json。

## 2026-09-21 PR-05 Pi protocol deployment

The paired backend/Agent release is deployed, with the concurrent ordinary material rebinding fix preserved. Runtime verification is recorded in reports/PR-05-pi-runtime-verified.json: three backend services each match 454 source hashes, Agent matches 18 compiled files, invalid protocol/attempt probes are denied, and public/internal maintenance is normal. Next/egress/database/gateway containers were not recreated. No real financial execution or retry was initiated. PR-04 and PR-05 remain incomplete; PR-06 onward are not completed. Common retry policy still requires immutable risk provenance and reliable execution/exit facts before implementation.


2026-09-21：PR-05 新增数据库短暂连接故障后的心跳有效/过期/新代次3项PostgreSQL回归，相关111项通过。三服务租约源码哈希与受测源码一致。仅测试与记录更新，没有服务重启或真实财务写入。详见 reports/PR-05-heartbeat-outage.md。下一项为显式风险来源与自动/手动共用重试政策，完整目标保持未完成。
