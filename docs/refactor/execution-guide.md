# financial_pj 完整架构改造执行手册

> **用途：交给具备仓库读写、终端和测试能力的编码大模型，按任务顺序实施。**
> 本文交付的是实施规范，不是已经应用到仓库的代码补丁。文中的新增路径、接口、表、配置、测试和命令均属于待实现目标；不得把它们写进“已完成”报告。

| 项目 | 内容 |
| --- | --- |
| 仓库 | `ErenYeager2002/financial_pj` |
| 文档版本 | 2.0，完整执行规范 |
| 形成日期 | 2026-09-18 |
| 静态审查基线 | `2cd58e91348ff566250f03b882f22c46425bbe1f` |
| 本次复核结果 | GitHub `main` 仍指向以上提交 |
| 审查边界 | 已通过 GitHub 连接读取关键代码、配置、目录及上一版方案；未运行项目、全仓测试、生产数据库、容器或真实财务任务 |
| 全量检查边界 | 本次容器无法解析 GitHub 域名，未完成本地完整克隆、全仓 AST/重复率扫描；相关工作明确列入 PR-00，不能声称已完成全仓审计 |
| 执行环境 | 保留 Python/FastAPI、Next.js、PostgreSQL、现有 Worker、Agent/Harness 与 Pi Runtime；以待改仓库及实际授权环境为准 |
| 对上一版的关系 | 取代上一版 8 项粗粒度 PR 划分；本版使用 PR-00 至 PR-21。旧编号不能与新编号混用 |

## 阅读与执行导航

本文按“执行规则 → 现状证据 → 目标边界 → 数据与接口设计 → 22 个实施任务 → 测试 → 上线回滚 → 删除条件 → 交接提示词”的顺序组织。

**给编码模型的最低阅读集合：** 开始任何任务前，先读第 1、2、4、5 章；再读当前 PR、相应测试用例和迁移/发布章节。涉及核销写入，必须额外读完整的核销不变量、恢复矩阵和事务边界。不要只读某个任务标题就开始批量改文件。

## 目录

- [1. 给执行模型的总指令](#chapter-1)
- [2. 已确认的现状与优先问题](#chapter-2)
- [3. 目标架构与依赖规则](#chapter-3)
- [4. 不可破坏的不变量](#chapter-4)
- [5. 数据、事务与执行协议设计](#chapter-5)
- [6. 分阶段实施任务](#chapter-6)
  - [6.2 PR-00：建立真实基线，禁止猜测全仓状态](#pr-00)
  - [6.3 PR-01：数据库迁移只有一个入口](#pr-01)
  - [6.4 PR-02：明确事务，消除隐式提交穿透](#pr-02)
  - [6.5 PR-03：实现数据库幂等，拆分会话与命令](#pr-03)
  - [6.6 PR-04：执行前授权与撤权后的安全行为](#pr-04)
  - [6.7 PR-05：统一重试政策，补齐租约与代次](#pr-05)
  - [6.8 PR-06：修复调度公平性与维护任务饥饿](#pr-06)
  - [6.9 PR-07：拆 API 入口，公开服务边界](#pr-07)
  - [6.10 PR-08：核销公开端口与基础适配器](#pr-08)
  - [6.11 PR-09：拆取数、材料、预览与补取](#pr-09)
  - [6.12 PR-10：拆核销判定、证据与计划，保留 14 个阶段](#pr-10)
  - [6.13 PR-11：拆暂存、写入和写后校验](#pr-11)
  - [6.14 PR-12：拆发布、批次、恢复，收尾巨型 service](#pr-12)
  - [6.15 PR-13：Pi 命令、运行时关联与控制协议](#pr-13)
  - [6.16 PR-14：正式文件成果与任务查询统一](#pr-14)
  - [6.17 PR-15：统一 SkillRevision 与发布协议](#pr-15)
  - [6.18 PR-16：前端共用、BFF 与任务交互](#pr-16)
  - [6.19 PR-17：完整构建、部署归一与运行管理器归位](#pr-17)
  - [6.20 PR-18：有证据地退役旧 Native 与 legacy](#pr-18)
  - [6.21 PR-19：观测、资源限制、故障与性能基准](#pr-19)
  - [6.22 PR-20：清理重复代码、依赖和文档](#pr-20)
  - [6.23 PR-21：综合验收与发布交付](#pr-21)
- [7. 接口契约与实现补充](#chapter-7)
- [8. 数据库迁移、历史回填与一致性](#chapter-8)
- [9. 自动化测试清单](#chapter-9)
- [10. 测试与工具命令](#chapter-10)
- [11. 配置、环境和兼容开关](#chapter-11)
- [12. 生产发布与回滚 Runbook](#chapter-12)
- [13. 删除清单与证据要求](#chapter-13)
- [14. 最终验收与完成报告](#chapter-14)
- [15. 交给编码大模型的启动与续接提示词](#chapter-15)
- [16. 逐PR给模型的最小输入与输出](#chapter-16)
- [17. 常见实现陷阱检查表](#chapter-17)
- [18. 来源、证据与版本说明](#chapter-18)
- [附录 A：文件级修改索引](#appendix-a)
- [附录 B：任务调度清单格式](#appendix-b)

---

<a id="chapter-1"></a>

# 1. 给执行模型的总指令

## 1.1 本轮必须达到的结果

在不改变既有财务业务含义和正常使用能力的前提下，完成以下改造：

1. 建立实际调用图、回归基线、可重复构建和 CI；明确哪些代码运行、哪些只是历史兼容。
2. 将数据库迁移与服务启动分开；明确事务提交者，防止辅助函数隐式提交。
3. 统一幂等、执行前授权、租约、失败分类与重试政策；保留原有防重复写入约束。
4. 将应收核销从巨型 `workflow_service.py` 中按垂直业务切片拆出，消除双向依赖。
5. 保留固定工具、应收核销、Agent/Harness、新 Pi 会话的职责；按实际调用证据收敛旧 Native 命令路径。
6. 统一正式文件成果、任务查询、事件与审计的基础协议，而不强制统一全部业务状态机。
7. 统一 Skill 版本和发布协议，整理部署入口，消除必须依赖历史补丁镜像才能重建的问题。
8. 有证据地清理重复代码、旧前端组件、失效文档和兼容入口，保留历史任务读取与恢复能力。

**本轮默认不做：** 微服务拆分、Kubernetes、替换 Next.js/FastAPI、重写核销算法、全站替换 UI 模板、接入第二套 Agent 框架、引入 Redis/Celery/Temporal/对象存储作为必选依赖、新增财务产品需求、把真实数据送往新外部服务。

## 1.2 默认授权与生产边界

本手册默认授权编码模型在隔离开发分支中检查、修改代码、创建合成测试数据、运行隔离测试、生成迁移和发布脚本。

**本手册不等于允许操作生产。** 未另获明确授权，不执行生产迁移、重启、Skill 发布、真实核销、回写、凭据变更、停用用户、删除真实数据、push、merge 或创建远程 PR。这里的“PR”表示一个独立变更集，可在本地完成并报告，远程提交按实际授权处理。

必须遵守：

- 不读取、打印、复制生产 `.env`、数据库密码、API Key、Cookie、浏览器账号目录和 `credential.key` 内容。
- 不执行 `git reset --hard`、`git clean -fdx`、未审查的批量删除或整卷清空。
- 不覆写用户未提交改动。先记录 `git status`；冲突文件隔离处理。
- 不将数据目录、日志、回滚凭据包上传 GitHub、CI artifact 或聊天。
- 不在生产 API、RPA 或外部业务系统上“试一下写入”。核销测试使用合成材料与受控假连接器。
- 任何删除、历史回填、真实发布脚本默认 dry-run；实际应用需独立参数、明确目标、操作记录和权限检查。
- 不因无法访问生产日志就宣布旧路径无人使用。缺少证据时保留兼容层，交付验证步骤。
- 不因某测试原先失败而删除或放宽业务断言。记录既有失败与新增失败的区别。

## 1.3 每个任务的固定执行流程

每次只推进一个满足依赖的 PR：

```text
读取基线/约束/进度记录
    → 核对当前源码是否已经实现目标
    → 定位入口、调用者、数据表、测试和副作用
    → 写出本 PR 文件清单与事务边界
    → 先补失败用例或特征测试
    → 最小范围实现
    → 运行专项测试、兼容测试、静态检查
    → 更新合约/文档/迁移说明
    → 审查 diff、敏感信息与删除清单
    → 写入真实执行报告与恢复点
```

当前源码已实现某要求时，不再复制实现；以证据和测试标记 `already_satisfied`。源码与本文不一致时，以实际源码和业务不变量为准，更新映射；不能强行回滚到审查版本。

## 1.4 新建并持续维护的执行记录

下列均为**建议新增文件**，PR-00 创建，避免模型换会话后丢上下文：

```text
docs/refactor/
  README.md
  progress.md
  execution-paths.md
  source-map.md
  transaction-boundaries.md
  dependency-map.md
  compatibility-matrix.md
  deletion-ledger.md
  baseline-failures.md
  migration-ledger.md
  decisions.md
  test-matrix.md
  rollback-matrix.md
  reports/PR-00.md ... PR-21.md
```

`progress.md` 必须记录：基线 SHA、当前工作分支、已完成 PR、当前 PR、未通过测试、阻塞项、待执行命令、活跃兼容开关、下一个安全任务。不得使用“基本完成”“理论通过”代替结果。

每个报告格式：

```markdown
# PR-XX 执行报告
- 开始 SHA / 结束 SHA 或未提交 diff
- 目标及本次明确未改的范围
- 实际修改、新增、删除文件
- 数据库变更与兼容范围
- 测试命令、退出码、关键结果、脱敏日志路径
- 已知问题与未验证项
- 生产操作：未执行 / 已获授权执行的具体动作
- 回滚方案与不可逆影响
- 下一 PR 及其前提
```

## 1.5 什么时候停止，什么时候继续

出现潜在重复财务写入、跨用户访问、租约失效仍可发布、生产路径误用、迁移会丢历史记录、核销基线金额变化时，停止当前危险动作，保存证据，修复或标记阻塞。不能跳过门禁继续后面的发布或删除。

缺少外部系统、Docker 或专用测试能力时，可以继续完成与该条件无关的代码及离线测试，但必须将相关验收标为 `not_run`，不得标为成功。阻塞生产发布不等于阻塞所有开发工作。

## 1.6 不允许的“伪重构”

- 将大文件复制成多个大文件，旧逻辑继续运行。
- 新模块反向 import 旧 facade，再声称已经解耦。
- 添加一个 `utils.py` 装下所有业务和基础设施代码。
- 把旧表全量迁到新的“万能 tasks”表，丢失业务阶段。
- 将所有异常捕获为 `failed` 后统一重试。
- 仅修改前端按钮隐藏来修复后端权限。
- 用 AST 未发现静态引用证明动态插件、反射、部署脚本没有引用。
- 更换返回类型却手工修改 `generated.ts` 来消除类型错误。
- 为全仓格式化制造大量无关 diff，掩盖行为修改。
- 在财务写入链路上同时运行新旧实现进行线上“双写对比”。

<a id="chapter-2"></a>

# 2. 已确认的现状与优先问题

## 2.1 当前执行路径

| 路径 | 已确认入口 | 持久化/执行机制 | 改造结论 |
| --- | --- | --- | --- |
| 普通固定任务 | `run_service.py`、`worker.py`、`adapters.py` | `RunRecord`、DB 队列、独立 Worker、attempt 工作目录 | 保留并补强 |
| 核销日期与批次 | `workflow_service.py`、`ar_execution_runner.py` | `WorkflowSession/Action/Batch`、材料版本、确定性脚本 | 保留业务状态；拆依赖 |
| Agent/Harness | `agent-runtime/`、`routers/pi_harness.py`、生产 `worker-agent` | 受控阶段工具与 Worker 协作 | 先盘点实际职责，不与新 Pi 简单合并 |
| 旧 Native 命令 | `native_skill_service.execute_command` | API 请求内调用 UDS、创建普通 Run 记录 | 优先核查替代关系；有条件退役 |
| 新 Pi 会话 | `routers/pi_runtime.py`、`pi_runtime_service.py` | 文件目录会话索引、UDS manager、独立运行环境及 jobs | 保留，通过适配层对齐基础协议 |

证据见 [S03]—[S13]。表中“当前”仅指本次固定提交源码，不声称已验证生产所有路径均在运行。

## 2.2 需要处理的具体问题

| 编号 | 代码观察（静态审查） | 影响与处理 | 对应任务 |
| --- | --- | --- | --- |
| F01 | `workflow_service.py` 超过 8,000 行，AR runner 反向调用其私有方法 | 明确公开端口，按业务切片拆分 | PR-08～12 |
| F02 | 普通任务先按 owner+key 查找；旧 Native 用同一 key 关联会话 | 拆分幂等与会话语义，增加原子请求登记 | PR-03 |
| F03 | `emit_event(..., commit=True)` 默认提交 | 原子创建任务时可能穿透外层事务，先建立显式 append 接口 | PR-02 |
| F04 | `init_db()` 执行 Alembic，API 和 Worker 都调用 | 迁移独立进程、启动只检查 | PR-01 |
| F05 | 自动重试 `_run_is_retryable()` 与手动 `retry_status()` 条件不同 | 统一风险政策，缺少风险字段不能按只读放行 | PR-05 |
| F06 | 普通 heartbeat 校验 attempt 和未过期，workflow heartbeat 未采用相同条件 | 先补过期/代次测试，再补齐 workflow fencing | PR-05 |
| F07 | 普通领取只查看前 100 条候选再按并发跳过 | 增加公平性，避免饱和 Skill 阻塞可执行任务 | PR-06 |
| F08 | 业务 Worker 空闲时兼做清理和发布维护 | 维护任务可能饥饿，明确调度份额或独立现有职责 | PR-06、19 |
| F09 | 新 Pi 会话在文件目录，旧 Native 又有独立命令生命周期 | 统一索引/关联，避免两套事实互相覆盖 | PR-13～14 |
| F10 | 网页源码更新与宿主机单工具发布未统一 | 共用发布状态与版本事实，保留多入口 | PR-15 |
| F11 | 存在基于历史日期镜像 COPY 个别文件的 Dockerfile | 建立完整源码构建和明确版本清单 | PR-17 |
| F12 | 当前文档数量、数据库、认证说明并非完全一致 | 自动生成事实性目录；历史决策移入历史文档 | PR-00、20 |

F05 的观察具体为：自动重试检查 adapter 非 RPA、风险 level 默认 `read_only`、attempt 上限；手动重试还检查 `modifies_uploaded_files`、Skill 版本、文件和权限等。这里是政策口径差异，不能据此声称已经发生重复写入。F06 同理，属于必须验证并补强的条件差异。[S04][S14][S15]

## 2.3 已有安全能力不能重复造或删除

已有普通 Run 的 `run_fencing.py`、`attempts/<attempt>` 工作目录、不可变材料版本、Artifact/Approval 绑定、核销阶段契约、写后失败分支、Pi 会话权限复核和 jobs 操作，均应先读再复用。[S05][S06][S07][S09][S10][S19]

`web/src/features/agent-runtime/` 的同名目录不是独立引擎的充分证据；本次已读目录中只有 `agent-wire.ts`。同样，`sources/`、`skills/`、`standalone-skills/`、`native-skill-overrides/` 不能仅按目录名判为重复。[S27]

## 2.4 优先顺序

P0：授权、幂等、事务、租约、重试、错误恢复、迁移安全。

P1：核销模块边界、Pi 对齐、版本发布、完整构建、文件一致性。

P2：公平性调优、页面共用、依赖清理、旧模式退役、文档整理。

出现与风险分类不同的真实证据时可调整顺序，但必须在 `decisions.md` 解释，不能以“先做容易的”无限推迟 P0。

<a id="chapter-3"></a>

# 3. 目标架构与依赖规则

## 3.1 目标保持模块化单体

```text
Next.js 页面 / 同源 BFF
        │
        ▼
FastAPI API 与应用服务
        ├── identity：本地身份映射、授权、业务作用域
        ├── skills：目录、不可变版本、发布协议
        ├── execution：幂等、执行引用、风险、租约、事件
        ├── files：正式文件登记、引用、访问与保留
        ├── approvals / audit：审批与事实记录
        └── assistant：模型配置、允许的工具、脱敏上下文
                │
        business/reconciliation、consolidation
                │
        现有 Worker / Agent Harness / Pi 运行适配器
                │
        受控脚本、专属工作区、沙箱、业务连接器

PostgreSQL：业务事实与平台索引
文件系统：固定源码包、原始材料、临时工作区与不可变成果
独立 manager：管理执行环境，不能把其权限交给普通模型工具
```

## 3.2 目标目录

以下为**目标目录**，不表示当前已存在；随对应 PR 渐进落地，不整体移动仓库。

```text
backend/app/
  main.py                         # composition root、middleware、router 组装
  modules/
    identity/                     # 第一轮可只放公共授权 facade
    execution/
      contracts.py
      idempotency.py
      idempotency_models.py
      submission.py
      authorization.py
      risk_policy.py
      lease_policy.py
      events.py
      query.py
    files/
      storage_port.py
      artifact_service.py
      reference_service.py
    skills/
      revisions.py
      release_contract.py
      release_service.py
    assistant/                    # 逐步包装已有模型服务，禁止另造 Agent
  business/
    reconciliation/
      api.py
      facade.py
      ports.py
      domain/
      application/
      adapters/
    consolidation/                # 等普通 adapter 特例抽取时再落地
  infrastructure/
    database/
    processes/
    storage/
    runtime/
  worker.py                       # 保持入口兼容，内部逐步委托
  models.py                       # 保留现有 ORM 元数据入口
  workflow_service.py             # 过渡 facade，最终不承载 AR 核心逻辑

runtime-manager/                   # 按 PR-17 迁移宿主机运行源码
agent-runtime/                     # 保留，先明确职责
web/src/features/                  # 保留现有 feature 结构，不第一轮批量重命名
deploy/                            # 正式声明式配置与部署入口
contracts/                         # API 与跨运行时版本契约
docs/refactor/                     # 实施记录
tests/                             # 保留现有根测试，新增集成/故障测试按现有约定组织
```

## 3.3 依赖约束

- API router 可调用应用服务，不直接启动财务子进程，不做 Excel 财务计算。
- 核销 domain 不依赖 FastAPI、SQLAlchemy Session、HTTP 客户端或模型 SDK。
- application 可以使用 repository/port，不反向 import `workflow_service` 或 `main`。
- adapters 实现 domain/application 声明的端口，不要求 domain 了解磁盘路径和容器。
- Worker 只负责领取、租约、执行适配和结果登记，不再增加 `if skill_id == ...` 业务分支。
- 现有合并报表在 `adapters.py` 中有特例，应在业务回归覆盖后抽成扩展钩子，不与核销重构同时改算法。
- 旧 facade 只单向委托。禁止双向 import、循环委托、复制一份逻辑作为“临时兼容”。
- 新模块名称可以按实际规范调整，但必须更新 source-map；不能为了让目录看起来整齐新增空模块和无用途抽象。

## 3.4 开源参考如何落实

Windmill 的服务端/Worker/PostgreSQL 队列分离，支持本项目继续沿用已有 DB 队列，而非无依据增加中间件。[E01]

Activepieces 的组件版本固定机制可用于补齐 SkillRevision 和运行快照之间的关系；这里不复制它的完整编排引擎。[E02]

Dify 的模型、工具和 AI 工作流组织用于约束 assistant 能力层；不能让其替代核销的确定性发布规则。[E03]

Midday 的财务文件、任务和助手组织方式用于前端信息架构，不照搬其用户/租户/商业模型。[E04]

这些是设计借鉴。实际复制第三方代码、镜像或组件前，另行核验许可证、版权声明与企业功能限制；本手册不宣称任何项目可无条件嵌入闭源企业系统。

<a id="chapter-4"></a>

# 4. 不可破坏的不变量

每个变更必须在报告中写明影响下列哪些不变量，以及对应测试。

| ID | 不变量 |
| --- | --- |
| I01 | 用户身份与角色从已验证会话及本地账号读取，不信任客户端 owner/department/role |
| I02 | 文件读取、选择、复制、登记、下载、删除分别鉴权；同内容 hash 不代表有访问权限 |
| I03 | 固定工具权限与 `native--<id>` 权限保持明确映射，不通过改名扩大授权 |
| I04 | 任务创建、确认、真正开始及高风险步骤都要满足当前授权；权限快照仅用于审计 |
| I05 | 执行模式、Skill 快照、业务日期、材料版本在任务生命周期内固定 |
| I06 | 金额、币种、期间、舍入、核销匹配规则由确定性业务代码决定 |
| I07 | 原始上传文件不作为可写工作区；写入使用隔离副本 |
| I08 | 任务产物发布之前验证输出 schema、文件边界和必要业务条件 |
| I09 | 材料版本历史不可覆盖；恢复历史材料应创建新的版本 |
| I10 | 同一材料作用域的合法当前版本只能有一个 |
| I11 | 多日期核销保持原有日期升序串行；已成功日期不重复执行写入 |
| I12 | 已失效的 Worker 不能发布结果、更新终态或续活已失效的租约 |
| I13 | HTTP 超时、进程失联、回读失败均不能推断“尚未写入” |
| I14 | 不确定财务写入禁止自动重试；只能执行明确且有证据的恢复动作 |
| I15 | 用户确认与管理员审批含义不同；只有实际存在的阶段才显示相应操作 |
| I16 | 模型建议、自然语言“确认”不能绕过后端硬闸和明确授权 |
| I17 | 凭据不进入模型上下文、任务参数、日志、命令行和普通容器环境 |
| I18 | 核销证据、材料、错误展示经过统一脱敏与受限分页 |
| I19 | 任务中心为查询投影，不得改变底层对象生命周期 |
| I20 | 批次与子日期的统计口径不能因统一任务中心而重复计数 |
| I21 | 临时 Pi 工作区文件不自动成为正式台账或核销材料 |
| I22 | 新旧执行实现不得在生产同时产生同一财务副作用 |
| I23 | 取消请求与取消完成分开；有未确认进程或副作用时不假报已取消 |
| I24 | 迁移不静默合并、丢弃历史任务和重复 key，不篡改审计事实 |
| I25 | 新功能回退不等于撤销财务写入；回退代码与修复业务数据是不同流程 |
| I26 | 配置/版本切换仅影响允许接收的新任务，不改变运行中固定契约 |
| I27 | 无证据的旧代码不删除，无证据的旧任务不重跑 |
| I28 | 原生沙箱可以保留已批准的通用命令能力，但不得因此获得正式财务写入和全局凭据权限 |
| I29 | 所有调用路径的原子性由数据库约束、事务及执行协议共同保证，不仅靠前端禁用按钮 |
| I30 | 本地测试成功不等于 PostgreSQL 并发、Linux UDS、Docker 隔离或生产发布已验证 |

<a id="chapter-5"></a>

# 5. 数据、事务与执行协议设计

本章是编码约束。类型名和新增表名为拟定名称；实施前核对现有模型，存在等价结构则扩展或复用，不新建同义数据系统。

## 5.1 必须区分的标识

| 标识 | 含义 | 不能替代 |
| --- | --- | --- |
| `request_id` | 一次 HTTP/应用调用追踪 | 幂等键、任务 ID |
| `idempotency_key` | 同一作用域同一逻辑提交的重放 | 会话归属 |
| `command_id` | Pi/Native 会话中的一条命令 | 整个会话 ID |
| `session_id` | 一段交互会话 | 普通 Run ID |
| `execution_ref` | 跨路径查询引用，包含 kind 和 id | 通用可写任务表 |
| `attempt` | 一个可重试执行的代次 | 客户端重试次数 |
| `lease_generation` | 领取资格版本；可直接复用已存在 attempt | Worker 名称 |
| `skill_revision_id` | 一个固定发布版本 | 分支名 main |
| `material_set_id` | 固定财务材料版本 | 最新文件名 |
| `plan_fingerprint` | 待执行写入计划摘要 | 任意参数 JSON hash |

普通执行建议使用 `kind=run`，核销使用 `workflow`/`workflow_batch`，Pi 使用 `pi_job`。返回原始 ID，不能把 UUID 截短作数据库主键。前端 key 使用 `kind:id`，防不同来源碰撞。

## 5.2 幂等登记表

建议新增 `idempotency_requests`，最小字段如下。字段类型、命名长度依现有 SQLAlchemy 规范实现；下面不是要求直接复制的 DDL。

| 字段 | 约束与用途 |
| --- | --- |
| `id` | UUID 主键 |
| `owner_id`, `department_id` | 非空，从服务端身份获取 |
| `operation` | 非空，例如 `run.create`、`workflow.start`、`pi.command.submit` |
| `request_key` | 非空、有长度限制；拒绝控制字符 |
| `request_fingerprint` | 64 字符 SHA-256 |
| `canonical_version` | 规范化算法版本，避免升级后误判 |
| `status` | `preparing` / `prepared` / `bound` / `rejected` |
| `reservation_token` | 处理占位的随机令牌，条件更新防旧处理者继续落库 |
| `reservation_expires_at` | 准备过程租约，不是业务执行租约 |
| `pinned_revision_json` | 固定 Skill/协议/模型选择等必要元数据；禁止存 API Key |
| `prepared_payload_json` | 已验证、冻结的执行输入；敏感信息按既有策略处理 |
| `execution_kind`, `execution_id` | 绑定真实业务记录，允许准备阶段为空 |
| `response_version` | 最小回放响应版本，不保存短期下载 URL、Cookie 或完整日志 |
| `created_at`, `updated_at` | timezone-aware |

唯一约束：`(owner_id, department_id, operation, request_key)`。操作范围必须由服务端固定，不能允许客户端任意构造 operation 规避约束。

保留完成后的轻量幂等登记/墓碑，不能默认按 24 小时删除导致长延迟客户端重复产生任务。保留周期由业务和历史保留政策确定；默认不主动过期有财务执行关联的记录。

## 5.3 请求规范化规则

指纹应基于语义明确的**提交内容**，与模型解析后的执行输入分开存储。

```text
operation + canonical_version
+ 服务端 owner/department
+ Skill 身份与本请求固定的 revision
+ 原始自然语言请求
+ 已提交结构化参数
+ 按 role 表示的文件 ID 与 SHA-256
+ 业务日期、材料版本、显式执行模式
+ 影响结果的模型选择/选项
```

要求：

- JSON 对象键排序；数组默认保持顺序。仅字段 schema 明确为集合时才排序去重。
- 不全局 trim 用户描述，不模糊匹配文件名，不使用 `str(dict)` 计算 hash。
- 拒绝 NaN/Infinity；金额按现有领域规则使用 Decimal 或规范化字符串，不能在这一轮将所有历史数字格式批量改变。
- 默认值由服务端补齐并固定；“今天”“最近文件”“当前版本”只能在第一次提交时解析，重放不得按新日期或最新版本重新解释。
- key 命中后，使用原请求已固定的 revision 比较，不能先解析 registry 最新版再判断冲突；否则发布新版本会破坏旧请求重放。
- 若客户端明确提交了不同版本或不同材料，即使其余内容相同，也返回冲突。
- 保留原提交摘要供故障核查，但不存全局凭据。
- 多次调用同一 key 时，即使浏览器刷新，也不重复触发模型解析。

## 5.4 幂等创建采用短事务分段

不得在数据库全局调度锁或长事务中等待 LLM、文件大复制或 UDS。

```text
A. 认证、基本 schema 校验、作用域确认
B. 短事务：原子插入或读取幂等登记；固定 revision/输入引用；领取准备 token
C. 事务外：读取受控材料、必要模型解析、生成不可变准备结果/快照暂存
D. 短事务：复核 token、身份、文件与 revision；保存 prepared 数据
E. 短事务：创建真实 Run/Workflow 与最初事件；登记引用；将幂等登记标为 bound
F. 提交后返回资源引用，后续由既有执行路径领取
```

D/E 可在准备完成后合并为一个短事务。所有业务记录、步骤记录、初始事件、幂等绑定必须同事务成功或同事务失败。

并发冲突通过唯一约束和 `ON CONFLICT` 或等价原子操作解决。不能“先 SELECT，没找到再 INSERT”后只依赖进程内锁。SQLAlchemy 异常后必须明确回滚或使用正确的 savepoint；`begin_nested()` 不是另一个独立提交事务。[E05]

响应约定：

- 同 key 同请求已 bound：按原接口兼容状态返回原资源，不再执行模型解析。
- 同 key 不同请求：409，错误码 `IDEMPOTENCY_CONFLICT`。
- 同 key 同请求准备中：使用已版本化的提交接口返回 202 与 request receipt；旧接口在未适配前保留其形状，可返回明确 `SUBMISSION_IN_PROGRESS` 409，而不是伪造 Run。
- 准备进程失联：在 token 到期后仅恢复**无业务副作用**的准备过程。已有 frozen payload 则复用；没有记录且无法确认模型结果时可能重新解析，但必须不重复执行财务动作，并记录解析尝试。
- 绑定提交成功但网络应答丢失：重放直接查到原资源。
- 身份撤销：即使 key 存在，也不能绕过当前读权限泄露原任务。

## 5.5 历史 Native 会话迁移

旧 Native 将 `workspace.parent.name` 写入 Run 的 `idempotency_key`。这代表会话哈希，不代表命令唯一性。[S08]

建议给普通 Run 增加可空 `source_session_key`、`source_command_id`，或使用等价独立关联表。具体选择在 PR-03 确定，但不得建立第二套执行事实表。

回填仅针对 `adapter == native` 且 key 满足已验证旧格式的记录；每条命令使用其 Run ID 派生稳定 command ID，保留原 key 不覆盖。回填不能从会话哈希反推出原始用户会话字符串。新代码优先读新字段，未回填才走旧字段 fallback；两个查询必须都限制 owner、department、adapter。

**禁止给现有 runs 全表直接添加 owner+key 唯一约束。** 历史空 key 和 Native 会话共用 key 都需要保留。

## 5.6 事务所有权

新增 `append_run_event()`、`append_audit_event()` 或具有同等语义的内部接口：只 add/flush，不 commit。旧 `emit_event` 可作为过渡 wrapper 保留原默认值，但新原子提交路径不再使用其隐式 commit。

事务边界由应用服务或 Worker 阶段控制。不要全局把 `commit=True` 改成 False 后依赖路由“碰巧提交”。需要逐调用点迁移，审查 `flush`、autoflush、ORM event listener、回滚后的实例过期等行为。

禁止在 `get_db()` 的 finally 中无条件 commit。异常请求不得提交半成品。

## 5.7 执行资格与发布资格

资格至少绑定 `(kind, id, worker_id, attempt/generation)`，且状态允许、租约未到期。旧 Worker 的续租、事件、成果登记、材料发布和终态更新均要受到资格检查。

数据库 fencing 只能阻止受控数据库发布，不能自动撤销已经执行的文件写入或外部系统动作。外部副作用必须依靠阶段检查、隔离工作区、确定性请求标识、回读与恢复政策补充。

所有持锁操作列入统一锁顺序表。第一轮沿用现有调度锁，并明确行锁获取顺序；不能局部改成先锁任务、另一路仍先锁全局锁，制造死锁。

## 5.8 错误类别与员工呈现

| 错误码 | 语义 | 自动处理 |
| --- | --- | --- |
| `VALIDATION_FAILED` | 参数/文件不满足要求 | 修正后用新 key 提交 |
| `AUTHORIZATION_REVOKED` | 当前权限不允许继续 | 停止新步骤，提供合法取消/查询 |
| `IDEMPOTENCY_CONFLICT` | 同 key 异参 | 不创建任务 |
| `MATERIAL_VERSION_CONFLICT` | 固定材料不再是允许发布基线 | 拒绝发布，不能悄悄换成最新材料 |
| `LEASE_LOST` | 当前执行者失去资格 | 不发布、不篡改新代次 |
| `EXECUTION_OUTCOME_UNKNOWN` | 未确认执行是否完成 | 回查，不自动重发写入 |
| `POST_WRITE_VERIFICATION_FAILED` | 写入已发生，校验失败 | 只允许证据支持的校验恢复 |
| `PUBLICATION_INCOMPLETE` | 结果已部分发布/登记未完成 | 进入原有恢复流程 |
| `ARTIFACT_PERSIST_FAILED` | 执行与归档状态不一致 | 优先恢复归档，不能重复计算写入 |
| `RUNTIME_UNAVAILABLE` | 控制面不可达 | 区分未提交与已提交未知 |
| `CANCEL_PENDING` | 请求取消但尚未安全终止 | 继续查询，不假报已取消 |

公共 API 错误应有 `code`、员工可理解 message、request_id、允许的恢复动作。详细堆栈进入受控管理员日志，不把绝对路径、凭据或完整财务记录返回浏览器。

## 5.9 统一执行查询不统一所有写模型

`ExecutionRef`/`TaskCenterItem` 只做投影。保留 Run、Workflow、Batch、Pi Job 的状态事实来源。

Pi 投影字段必须含 `observed_at`、`source_status`、`sync_state`。运行时失联显示“状态待确认”，不能把缓存 `running` 当实时，也不能自动改成 `failed`。若为了查询增加运行时关联表，仅登记 runtime_id、session、command、scope、最后观察序号、artifact 引用；不再启动新的队列。

## 5.10 数据库变更最小清单

| 逻辑迁移 | 内容 | 默认是否必须 |
| --- | --- | --- |
| M01 | 幂等登记与 Native 专用关联字段 | 必须，PR-03 |
| M02 | 领取扫描与作用域查询索引 | 由执行计划验证后加入 |
| M03 | Workflow 执行代次所需字段 | 现有 attempt 足够则不加 |
| M04 | Pi 运行时关联索引/命令回执 | 现有结构不能表达时加入 |
| M05 | Skill 发布/版本字段 | 优先扩展现有 source/rollout 模型 |
| M06 | 文件引用登记覆盖 | 先复用 ArtifactBinding；缺少会话引用才补最小表 |
| M07 | Pi 会话目录数据库化 | 单机本轮不强制；多主机需求另行开启 |

禁止一开始创建所有目标表。每个新增表必须写“现有哪个模型不能表达”“哪个真实调用使用”“如何迁移和回滚”。不做纯愿景型持久化。

<a id="chapter-6"></a>

# 6. 分阶段实施任务

## 6.1 任务总表与依赖

本版共 22 个独立变更集。默认顺序执行。只可并行处理无共享代码、数据库和协议的文档/测试准备；不得并行修改 `models.py`、迁移头、`workflow_service.py`、核心合约或发布入口。

| PR | 目标 | 依赖 | 核心门禁 |
| --- | --- | --- | --- |
| PR-00 | 全仓盘点、合成基线、环境与 CI 准备 | 无 | 获得真实调用/测试基线 |
| PR-01 | 独立迁移与启动版本检查 | 00 | API/Worker 不再隐式迁移 |
| PR-02 | 显式事务与事件 append 接口 | 00、01 | 回滚无半成品任务 |
| PR-03 | 幂等登记、命令/会话语义拆分 | 02 | 并发相同提交仅绑定一个执行 |
| PR-04 | 执行阶段授权与撤权规则 | 02、03 | 撤权后不能开始新危险步骤 |
| PR-05 | 重试统一、租约与代次防护 | 02、04 | 旧 Worker 不能续租或发布 |
| PR-06 | 队列公平性与维护份额 | 05 | 并发限制不失效、队列不饥饿 |
| PR-07 | API 拆分与公开服务边界 | 02～05 | 原 API 合约兼容 |
| PR-08 | 核销公开端口和基础适配器 | 07 | 新模块不反向依赖旧 service |
| PR-09 | 核销取数、材料与预览切片 | 08 | 取数与材料基线不变 |
| PR-10 | 核销判定、计划、证据切片 | 09 | 原 14 阶段顺序保持 |
| PR-11 | 核销暂存、写入、写后校验 | 10 | 禁止重复写入与错版本写入 |
| PR-12 | 核销发布、批次与恢复切片 | 11 | 已完成日期不再写入 |
| PR-13 | Pi 命令关联、运行时协议 | 03～05、07 | 重放命令不重复启动 |
| PR-14 | 正式成果、引用与统一查询 | 12、13 | 文件权限、引用和统计一致 |
| PR-15 | Skill 版本及发布协议收敛 | 05、12～14 | 多入口只有一套发布事实 |
| PR-16 | 前端共用、BFF、任务交互 | 07、13、14 | 页面与历史链接兼容 |
| PR-17 | 完整构建、运行管理器归位 | 01、13、15 | 不依赖日期补丁链可重建 |
| PR-18 | 旧 Native/legacy 分阶段退役 | 13～17 | 无活跃依赖才删除执行入口 |
| PR-19 | 观测、故障演练与性能基准 | 05、06、12～17 | 关键风险可见、演练通过 |
| PR-20 | 重复代码、依赖、文档清理 | 18、19 | 有证据删除，保留来源与历史 |
| PR-21 | 综合验收与分批发布包 | 全部必选门禁 | 验收表完整且回滚可用 |

上一版对应关系：旧 PR-01 → 新 00/20；旧 02 → 新 02/03；旧 03 → 新 01/04/05；旧 04 → 新 13/18；旧 05 → 新 08～12；旧 06 → 新 15/17；旧 07 → 新 07/14/16；旧 08 → 新 06/19。

<a id="pr-00"></a>

## 6.2 PR-00：建立真实基线，禁止猜测全仓状态

### 修改位置

现有：`README.md`、`CONTEXT.md`、`docs/ARCHITECTURE.md`、`backend/pyproject.toml`、`web/package.json`、`backend/tests/`、`tests/`、`web/tests/`、`deploy/`、`deployment/`。

新增：第 1.4 节执行记录；`scripts/refactor/` 下只读盘点与隔离测试入口；仓库根 CI 配置（先检查实际是否存在外部 CI，不重复替代）。

### 具体步骤

1. 在用户工作副本运行 `git status --short`、`git rev-parse HEAD`、`git log -1 --format=%H`。记录本地 SHA 与本文基线差异。分支创建不得覆盖已有同名分支。
2. 阅读根 `AGENTS.md`、子目录 `AGENTS.md`、现有项目约束；记录冲突。不要把文档中的 TODO 当已实现功能。
3. 使用 `git ls-files` 获取受版本控制文件清单，排除 `.git`、依赖、生成文件和用户数据。脚本不得递归扫描真实 `data` 内容。
4. 对 Python 使用 AST 列出顶层类/函数、import、路由装饰器、`commit/rollback/flush`、`subprocess`/文件写入、动态 import、入口点。不能只按行数识别职责。
5. 对 TS/TSX 列出 App Router 路由、BFF、页面、组件、hooks、查询 key、模型调用、动态 import、CSS 和构建依赖；使用现有 TypeScript 工具链，不新增大型扫描服务。
6. 比较 `skills`、`sources`、`standalone-skills`、`native-skill-overrides`：按相对路径和 SHA-256 分组，记录精确重复、近似重复、vendor 副本、自动生成文件。不能自动删除。
7. 盘点所有 Compose、Dockerfile、systemd、计划任务、PowerShell 启动器和真实入口。将“代码存在”“配置引用”“实际启用”“有调用证据”分四列。
8. 建立隔离合成数据：普通表格任务、多个年份账簿、一份流转表、单日与多日取数包、写后失败、Native/Pi 文件生成。每个 fixture 注明构造逻辑和预期业务含义。
9. 收集原有测试结果与环境阻塞；先使用现有测试入口，不导入全局 settings 后才修改测试数据库。
10. 建立 CI：格式/类型、后端单元、PostgreSQL 集成、OpenAPI 生成差异、前端 build、关键合成 E2E。Linux 上覆盖 `fcntl`/UDS；不能仅 Windows 或 SQLite 通过就算完整。

### 盘点脚本的实现要求

建议实现 `scripts/refactor/inventory.py`：默认只读取 tracked files；输出 JSON 和 Markdown；字段包含 path、language、symbol、start/end、imports、side_effect_hints、generated/vendor 标记。报告不包含源码密钥或 `.env` 内容。

建议实现 `scripts/refactor/duplicate_report.py`：默认输出候选，不修改文件；精确 hash 与规范化代码相似度分开；license/vendor 目录标注保护；输出“重复源码”的判断依据。

建议实现 `scripts/refactor/verify_isolation.py`：在任何项目模块 import 之前运行，检查专用测试标记、测试 DB 名称、主机允许列表、数据目录位于本轮临时根、路径不是 symlink 指向真实目录、执行写入和真实业务连接器关闭。环境名称 `test` 只有经 settings 支持后才使用，否则选择受支持的 development 加显式隔离配置。

### 验收

完成 execution-paths、source-map、baseline-failures；可从本地副本确定每条路径的入口和调用者；测试数据不依赖真实用户名、财务附件或 API Key。没有运行完整测试时明确列明缺项。

### 回滚

本 PR 不改业务运行行为；可撤销盘点和 CI 文件，但保留生成的审查报告。禁止“为了基线干净”重置用户工作区。

<a id="pr-01"></a>

## 6.3 PR-01：数据库迁移只有一个入口

### 修改位置

现有：`backend/app/database.py`、`backend/alembic/env.py`、`backend/app/main.py` lifespan、`backend/app/worker.py` run_loop、`deploy/production/compose.yaml`、开发/部署启动脚本及所有 `init_db()` 调用者。[S17][S18]

新增建议：`backend/app/infrastructure/database/migrate.py`、`schema_check.py`、隔离迁移测试。

### 具体步骤

1. 分离 `migrate_database()`、`check_schema_compatible()`、`seed_required_rows()`；用户初始化如 bootstrap_admin 独立处理并保证原子/幂等，不把所有初始化都删除。
2. `init_db()` 过渡为明确兼容 wrapper。生产 API/Worker 改用只检查入口；测试 fixture 显式调用迁移。不能保留“生产缺表自动建表”的 fallback。
3. 迁移命令先检查数据库目标、预期 revision、单一 head、迁移是否安全，再获取迁移互斥锁。锁失效或超时明确退出。
4. PostgreSQL 锁可以是专用连接上的 advisory lock；迁移过程必须持续持有该连接。若将连接传给 Alembic，要修改 `env.py` 使用 `config.attributes['connection']`，而不是重新创建无关 engine。现有 `env.py` 会自行创建 engine，必须处理这一点。[S18][E06]
5. 离线生成 SQL 不得要求连接生产数据库；online/offline 路径都保留。
6. 当前 `SQLITE_RUNTIME_COLUMNS` 的补列逻辑迁入正式 Alembic revision 或受控的一次性 legacy 升级入口。先验证旧 SQLite 样本，不直接删兼容逻辑。
7. 将“没有 alembic_version 自动 stamp 基线”的行为从普通服务启动拿走；仅允许 legacy 导入工具在验证已存在结构确实匹配后执行。禁止凭存在任意平台表就随意 stamp。
8. 将 `migrate_sqlite_to_postgres.py` 从日常 schema 升级命令中分离。首次数据导入与平常升级拥有独立报告和授权。
9. Compose 添加一次性迁移服务或显式预启动命令，让 API/Worker 在迁移成功后启动。注意 skill-sync 与迁移依赖不能形成循环。
10. schema 检查采用受支持 revision 集合/范围，记录当前和应用兼容版本。新旧应用并存时不能简单要求旧应用的 `head` 与新 DB 完全相同，必须配套 expand/contract 策略。

### 测试

全新 PostgreSQL、当前版本 PostgreSQL、旧 SQLite、已迁移再次运行、迁移失败、多迁移进程竞争、多 Worker 同时启动、数据库版本过旧/过新、未知分叉 head、无 DDL 权限的运行用户。

### 完成标准

API/Worker 正常启动期间不执行 `ALTER/CREATE/DROP`；迁移失败服务不 ready；重复 seed 不重复插入；日常启动不导入旧库。

### 回滚

采用向后兼容新增结构时回滚应用，不立刻 downgrade DB。移除字段/约束的 contract 迁移推迟到 PR-21 后独立批准，不能借代码回退删除新业务数据。

<a id="pr-02"></a>

## 6.4 PR-02：明确事务，消除隐式提交穿透

### 修改位置

`events.py`、`audit_service.py`、`run_service.py`、`draft_service.py`、`step_runtime_service.py`、`storage.py`、普通任务路由；`authorization.replace_user_permissions()` 的默认提交另列管理操作事务审查，不在同一 PR 全面改写。[S14][S28]

### 具体步骤

1. 生成全仓 commit 调用表，区分：API 用例提交、Worker 领取提交、阶段检查点提交、独立 heartbeat 提交、辅助函数隐式提交。
2. 新增纯追加 `append_run_event(db, ...)`；它可以修改 run 的相关字段、add 事件、flush，但不 commit。对应失败审计也仅追加。
3. 保留 `emit_event` 旧行为作为短期 wrapper，逐路径替换。禁止全仓字符串替换默认 commit。
4. 把普通任务提交拆为 prepare 与 persist，persist 接受调用方事务。所有 `RunRecord`、StepRun、文件绑定、ModelTrace、初始事件同事务创建。
5. 为 `create_run`、`confirm_run`、`cancel_run`、草稿消费明确唯一 commit 者。内部服务可抛领域异常；HTTP 层按现有形状映射。
6. 数据库事务外的大文件复制写到唯一暂存目录，数据库绑定失败仅留下可回收孤儿；不能在事务回滚处理里删除可能已经被另一请求引用的目录。
7. 长操作的进度事件单独短事务写入，仍校验执行资格；不能让进度提交意外把未完成材料发布一起提交。
8. 审查 `run_fencing` 的 Session `before_flush` 监听器。提交路径无 run fence 时不得误报；Worker 路径不能因换 Session 丢失 fence。
9. 回滚后重新读取必要 ORM 实例，不继续使用失效事务中的对象假定其状态已保存。

### 测试

在创建 run、创建 steps、追加事件、追加审计、绑定文件后分别注入异常，提交必须整体不存在；明确在“响应丢失但提交已完成”时全部存在。失败审计不含密钥。

### 完成标准

transaction-boundaries 标明每个用例的 commit 者；不出现两个不同服务共同依赖隐式提交；旧事件接口的调用量可追踪。

### 回滚

仅回退新调用路径，保留旧 wrapper；不能回退到已产生半提交错误的实现继续服务。事务变化回退也需要专项测试。

<a id="pr-03"></a>

## 6.5 PR-03：实现数据库幂等，拆分会话与命令

### 修改位置

`run_service.create_run/retry_run`、`draft_service.py`、`native_skill_service.py`、相关请求 schema、普通任务 BFF/前端提交逻辑、`models.py` 元数据入口、Alembic 新 revision。

新增建议：`modules/execution/idempotency_models.py`、`idempotency.py`、`submission.py`。

### 实施步骤

1. 按第 5.2～5.5 节实现表与字段，索引命名沿用项目规范。新模型通过现有元数据入口显式导入，避免 Alembic autogenerate 漏表。
2. 先做 dry-run 历史分析：普通 key 重复组、空 key、Native 共用 key、同 key 不同输入、跨部门历史记录。只输出 ID 和脱敏摘要，不自动合并。
3. 实现带版本的 canonical request 与 SHA-256。为数组顺序、默认值、Decimal、Unicode、文件角色、时间日期单独写测试。
4. 实现 reserve/read/mark_prepared/bind/reject 的条件更新 API；token 不匹配、租约失效不能 bind。
5. 对 `create_run` 使用短事务准备协议。外部模型解析只能在占位成功后发生；第一次已保存的解析结果供重放复用。
6. 快照复制防 TOCTOU：先固定 revision/hash，复制至 staging 后重新核对；source 在复制中变化则拒绝，不生成名不副实的快照。
7. `retry_run` 明确是“创建新的业务执行”还是“重放同一次重试请求”。当前 `retry:<run_id>` 的含义先通过测试固定，不能让用户多次网络重试不断建新任务。
8. 草稿消费必须原子标记 consumed 并绑定 run，不能任务成功创建而草稿仍可重复消费。
9. 幂等 key 由前端在一次用户提交意图开始时生成并持久到提交结束；网络重试复用，用户修改参数重新提交生成新 key。不要每次 fetch 自动生成新 key。
10. 新 API 内部 receipt 与旧创建 API 形状兼容，BFF 透传对应状态和 request_id；不在重复请求时返回最新不相干 run。
11. Native 新字段分批回填，保持旧字段只读 fallback；每批使用稳定游标和事务，输出已处理/跳过/异常计数。
12. 任何历史 key 组存在多条不同业务记录时标为 ambiguous，保留原记录，禁止自动选第一条当“正确记录”。必要时只为新请求启用强幂等。

### 专项测试

使用至少 20 个并发客户端对同 key/同请求提交，真实 PostgreSQL 上只有一个 bound 资源；同 key 异参 409；同 key 隔离不同 owner/department/operation；断在 prepared 后可恢复；断在 commit 后可重放；发布新 Skill 后旧 key 仍返回原固定版本；撤权不能借重放读取旧资源；同 Native 会话至少三条命令均可登记。

### 完成标准

幂等保证来自 DB 唯一约束与 token 条件更新，模型解析/快照/任务关联可解释，历史记录零丢失。禁止宣称对外部副作用达成“绝对 exactly-once”。

### 回滚

新表和字段保留。只允许回退到仍理解幂等绑定的兼容应用；不将已启用的新提交重新路由到未经幂等保护的旧 writer。已有 receipt 继续提供查询。

<a id="pr-04"></a>

## 6.6 PR-04：执行前授权与撤权后的安全行为

### 修改位置

`authorization.py`、`auth.py`、`run_service.py`、`worker.py`、`workflow_execution_policy.py`、`ar_execution_runner.py`、`pi_runtime_service.py`、`pi_skill_bindings.py`、`native_skill_policy.py`、确认/取消路由。

新增建议：公共 `modules/execution/authorization.py`，复用 `refresh_active_user`、`assert_skill_permission` 与已有资源归属检查，不复制权限模型。

### 实施步骤

1. 定义调用阶段 `create/confirm/start/read/write/publish/cancel`，明确每阶段检查列表。
2. Worker 从 DB 当前用户记录恢复身份；使用任务固定的 owner 和原 department 进行一致性检查，不以任务里的历史 role 直接授权，不把所有用户强制构造成 finance_user 而跳过真实权限逻辑。
3. 调用顺序必须先 refresh 再 assert，尤其管理员降权后不能继续通过旧 `is_admin` 快照绕过。
4. 排队阶段撤权、停用、部门变更：拒绝启动，生成脱敏可审计原因。改变旧任务归属只能通过独立数据治理流程，不能“自动跟随新部门”。
5. 写入前检查 Skill 操作权限、输入材料归属、审批/确认快照、固定版本、执行资格；用户权限变更不能用缓存延迟刷新当理由跳过。
6. 长事务中已进入不可逆原子步骤，不粗暴 kill。允许完成必要的停止、回读、校验和证据保存，但不自动继续下一个写入步骤。
7. 撤销运行权限后，合法用户仍应可停止自己会话或取消自己的待执行任务；账号停用导致无法登录时由管理员受审计地停止，不能给匿名用户 stop 权限。
8. 新 Pi 保留 stop/cancel 的安全豁免，但豁免的是 Skill 执行权限，不是身份、会话归属和部门隔离。
9. 前端只做体验提示，后端所有入口独立执行相同政策；不只修改某个普通 POST 路由遗漏草稿/Agent/Native 入口。
10. 高风险授权与落库之间采用已定义锁/CAS，记录授权观察版本；不声称跨外部系统操作具备绝对瞬时撤权。

### 测试

创建后撤权、确认后撤权、排队后停用、管理员降权、用户换部门、无权限直接调用 Agent 工具、Pi 挂载后权限变化、撤权后取消、其他用户猜 ID、管理员跨部门读写的既有政策。

### 完成标准

所有创建和执行路径拥有显式边界检查；新策略不扩大原有管理员跨部门权限；恢复操作使用明确权限而非假冒原用户。

### 回滚

保留安全检查；回退 UI 或非关键接口不移除后端政策。因新增检查拒绝旧任务时记录兼容问题，不能用全局 bypass 解决。

<a id="pr-05"></a>

## 6.7 PR-05：统一重试政策，补齐租约与代次

### 修改位置

`scheduler._run_is_retryable/recover_expired_jobs`、`run_service.retry_status/retry_run`、`leases.py`、`run_fencing.py`、`worker.py`、`workflow_service.run_workflow_action_once`、`ar_execution_runner.lock_execution`、相关 step runtime。[S04][S05][S15][S16]

### 风险政策

新增纯函数 `evaluate_retry_policy(snapshot, execution_facts, reason)`，返回 allowed/code/explanation，不直接更新任务、不调用网络。

自动重试必须同时满足：已知完整风险声明、明确只读、不会改原材料或外部系统、执行器允许安全重放、尝试次数未达上限、当前身份/文件可访问、没有不确定副作用记录、没有取消或待人工状态。需要 step 的 `is_idempotent/retryable` 时复用已有定义。

缺少字段、损坏 JSON、未知 adapter、旧 Native 的笼统 read_only 标记均不能自动放行。手动重试可增加更多输入/版本检查，但不能比自动政策更宽松地重复危险写入。

### 租约实施步骤

1. 普通 Run 沿用 `(id, worker_id, attempt)`，保留 Session before_flush 防护；增加结构化 lease_lost 观测。
2. Workflow heartbeat 必须绑定领取时的 `attempt_count` 或等价代次，且只更新尚未过期的有效租约；不靠固定 worker 名称识别唯一执行。
3. `run_workflow_action_once` 向 heartbeat 传递当前代次；AR lock 检查同一代次。两者先同步实现和测试，避免一边支持一边不支持。
4. heartbeat 条件更新返回行数 0 时记录资格失效；不无限“成功续租”假报。临时 DB 错误允许在未过期窗口内重试 heartbeat，但不延长一个已失效资格。
5. 领取时间与超时尽量使用一致的 DB 时间源；耗时测量用 monotonic。跨主机时钟差异列入测试，不用显示时间判断唯一执行者。
6. 明确 `waiting_user_action` 是否仍有活跃子进程/租约。现有 fencing 接受该状态，但 heartbeat/count 的处理要审查；若仍占执行槽则所有租约与容量检查必须一致，若释放则先保存检查点并明确转交，不简单扩大状态列表。
7. 终态更新、事件、成果登记、材料发布使用条件更新或持锁事务校验代次。不能仅在执行开始检查一次。
8. 旧 Worker 失去资格后不能把新执行状态改 failed/cancelled；只记录独立的脱敏观测，必要时停止自己唯一标识的子进程组。
9. 子进程停止必须绑定本次 process identity，不能按进程名杀所有 Python/浏览器。保留核销进程证据和现有特殊处理。
10. 租约过期不代表物理进程退出。对于写入动作保留 outcome_unknown/process_exit_confirmed=false，禁止自动重排。

### 故障测试

同 worker_id 不同 attempt、旧 heartbeat 延迟抵达、过期后 heartbeat、取消与领取竞态、发布与恢复竞态、DB 断连/恢复、waiting_user_action 容量、子进程还活着但 Worker 退出、进度事件尝试越权提交。

### 完成标准

自动与手动重试共享风险基础，任何不确定写入只进入恢复路径；Workflow 旧代次无法续租和发布；普通已有 fencing 测试不退化。

### 回滚

可能改变重试许可的配置只能更保守地关闭重试，不能回退为缺字段默认只读。旧实例不理解新 fencing 时禁止与新实例共同领取同一任务集合，使用维护排空/Worker 协议版本门禁。

<a id="pr-06"></a>

## 6.8 PR-06：修复调度公平性与维护任务饥饿

### 修改位置

`worker.claim_next_run/run_once`、`scheduler.py`、`workflow_service` 中 action claim、`task_discovery_worker.py`、清理和 rollout 调度入口。

### 第一轮实现

1. 保留现有全局调度锁，先修复前 100 条候选的问题，不同时改变所有锁策略。
2. 推荐按本池可运行 Skill 获取每个 Skill 最早的可领取候选，再按 oldest queued_at 和稳定 ID 排序。统计有效租约后跳过饱和 Skill；保证后面不同 Skill 可进入候选。
3. 如果采用分页扫描，必须使用 keyset 而非不断 OFFSET；预算耗尽时记录 continuation 并保证下次继续向后，不每次回到同一批饱和任务。
4. 候选选择、并发计数和领取状态更新必须处于同一受保护事务。授权失败任务记录终止原因后继续查其他候选。
5. 候选输入和 snapshot 校验不能持锁做大文件 hash 或远程网络。先做廉价过滤，文件完整性在实际启动前验证。
6. 定义并发作用域：保持原 Skill 级限制与各池关系，不擅自改成 owner 级。普通/核销/取数/Agent 的占槽语义写表，避免重复占槽或漏算。
7. 维护任务采用明确份额：在任务之间检查维护到期预算，或将清理等交给独立维护入口；不只在“没有任何业务任务时”才运行。不得从长财务写入中间抢占进程。
8. 维护服务多实例时也需要 DB 领取/锁，避免多个清理进程同时删同一个包。
9. 增加测量：最老任务年龄、每池队列长度、领取耗时、锁等待、饱和跳过次数、维护延迟。不在指标 label 中放用户/文件名。

### 后续优化门槛

只有测得全局锁成为瓶颈时，另做 ADR 引入 `FOR UPDATE SKIP LOCKED` 加每 Skill 容量槽/锁。PostgreSQL 的 SKIP LOCKED 可用于队列竞争，但不会自动保证业务并发上限和严格顺序。[E07]

### 测试

前 100 条饱和、第 101 条可运行；1000 条同类积压与多个新 Skill；多 Worker 竞争不超限；workflow batch 顺序；维护在持续有业务任务时仍能执行；领取失败事务回滚。

### 回滚

保留修复前后的调度路径只在测试可选；生产回退不改变已领取任务状态和代次。关闭公平性优化不能取消已运行任务。

<a id="pr-07"></a>

## 6.9 PR-07：拆 API 入口，公开服务边界

### 修改位置

`main.py`、现有 `routers/`、`contracts.py`、`schemas.py`、`resource_policy.py`、普通 run/file/model/catalog 路由，以及相应 BFF。

### 实施步骤

1. 将 `main.py` 中目录、模型连接、普通任务、文件、核销、工作台等路由按现有业务分组迁到 router。已有 router 复用，避免重复注册。
2. 保持 path、method、鉴权依赖、response_model、状态码、错误结构、流式语义。保留 operation_id 或记录必要变更，避免生成客户端突变。
3. `main.py` 仅保留应用组装、生命周期、middleware、OpenAPI 组装与基础健康入口。
4. 公共服务输入不接受未经检查的客户端 UserContext；依赖注入后的 Actor/Scope 为内部类型。
5. 普通业务逻辑从路由移到用例服务，不把 8,000 行 service 搬进 router。
6. 临时兼容 wrapper 明确导出符号，禁止使用 `from ... import *` 掩盖依赖。
7. 公共 exception 到 HTTP 的映射集中维护，但保持旧客户端所需 detail 形状。
8. API/OpenAPI schema 导出必须在无生产数据库、无真实模型 Key 的环境可执行；不得靠导入 main 触发生产初始化完成导出。
9. 如果抽到模块级 schema，保持 Pydantic 模型名称稳定并检查同名冲突；不要因新的重复类自动生成 `Schema2` 等未知类型。
10. 初步建立架构测试：新 business 模块禁止 import `app.main`，禁止反向依赖 facade；旧未迁移边逐条 allowlist 并绑定待清理 PR。

### 验收

生成路由与 OpenAPI before/after 差异；所有旧可用路径继续可用；没有重复注册路由、权限降级和错误体变化；main 的职责可逐条解释。

### 回滚

保留路由 facade 能委托原服务；不改变数据库。在同一提交中不顺便重命名前端所有 URL。

<a id="pr-08"></a>

## 6.10 PR-08：核销公开端口与基础适配器

### 修改位置

`workflow_service.py`、`ar_execution_runner.py`、`ar_execution_contract.py`、`ar_annual_materials.py`、`ar_process_evidence.py`、`ar_snapshot_contract.py`、`workflow_material_service.py`。

新增目标：`business/reconciliation/ports.py`、`domain/`、`adapters/`、`facade.py`。

### 先做符号迁移表

对每个迁移符号记录：旧路径与名称、调用者、读写表、文件副作用、是否提交事务、锁要求、涉及执行契约版本、测试位置、新路径。至少覆盖以下已确认的依赖：

| 已有符号/能力 | 新归属建议 | 迁移要求 |
| --- | --- | --- |
| `_run_script` 及受控脚本执行 | `adapters/snapshot_scripts.py` | 保留环境清理、超时、进程证据、退出码 |
| `_controlled_context_workspace` | `adapters/workspace_store.py` | 保留根目录/作用域/路径越界检查 |
| `_workflow_storage_root` | `adapters/workspace_store.py` | 不把旧历史目录规则丢掉 |
| `_annual_ledger_arguments` | `adapters/snapshot_scripts.py` | 年度映射来自固定材料，不重新猜测 |
| `lock_execution` | `application/execution_guard.py` | 与 scheduler、cancel、publication 锁顺序一致 |
| `execution_version` | `application/version_guard.py` | 批次首日与后续快照契约一致性 |
| `PHASES`、`require_phase` | `domain/phases.py` | 第一轮保留全部名称/顺序/进度 |
| 材料查询/发布 | `adapters/material_repository.py` | 包装已有实现，后续再迁移内部逻辑 |

### 端口形状

下面是接口设计约束，不是可直接运行的完整实现。按实际现有类型编写代码与错误映射：

```python
from typing import Protocol

class SnapshotScriptRunner(Protocol):
    def execute(self, request: "ScriptRequest") -> "ScriptResult": ...

class MaterialRepository(Protocol):
    def read_fixed(self, scope: "Scope", material_set_id: str) -> "MaterialSet": ...
    def publish_verified(self, request: "PublicationRequest") -> "MaterialSet": ...

class ExecutionGuard(Protocol):
    def require_phase(self, ref: "ActionRef", phase: str) -> None: ...
    def require_live_lease(self, ref: "ActionRef") -> None: ...
    def require_write_authority(self, request: "WriteGuard") -> None: ...
```

`ScriptRequest` 包含固定 Skill 路径引用、入口白名单、参数、工作区、允许退出码、timeout、进程证据关联；不允许模型传任意宿主路径或绕过风险分类。

### 实施步骤

1. 先移动纯常量、错误类型、值对象、阶段前缀检查；保留旧文件显式 re-export，避免持久化协议变化。
2. 抽出工作区定位、年度参数、受控脚本执行；保留真实引用的旧函数委托，删除复制的第二份实现。
3. 在 composition root 创建具体端口依赖，不在业务类内部 `from . import workflow_service as service`。
4. 去除 AR runner 对 service 的反向 import，改为显式依赖。每消除一条边运行对应特征测试。
5. 不在此 PR 改 SQL 结构、不改 workbook 算法、不变更 phase 名、不引入新任务队列。
6. 测试 monkeypatch 原私有函数的，迁移为注入 fake port；先保留行为断言，不删除测试以适配新结构。
7. `app.models` 继续作为 ORM 元数据入口，避免因为 domain 移动导致类重复注册。

### 验收

新 domain 无基础设施依赖；新 AR application 不反向引用 `workflow_service/main`；新旧 API 响应一致；旧快照脚本路径仍可执行；合成结果一致。

### 回滚

使用旧 facade 重新路由到旧组合方式，但不可同时执行两条业务路径。固定执行契约与数据库内容不变。

<a id="pr-09"></a>

## 6.11 PR-09：拆取数、材料、预览与补取

### 修改位置

`workflow_service.py` 内的创建/启动/取数/预览相关函数，`fetched_bundle_service.py`、`fetched_data_preview.py`、`workflow_material_service.py`、`service_credential_service.py`、`task_reminder_workflow_service.py`。

新增目标：`application/create_execution.py`、`fetch_data.py`、`review_fetched_data.py`、`material_selection.py`，与相应 repository/connector adapter。

### 具体步骤

1. 创建执行用例固定用户、部门、Skill revision、execution_mode、业务日期、材料版本、取数方式；后续不得自动替换其中任何值。
2. 日期范围沿用原 schema 限制和顺序。明确字符串日期是业务时区日期；数据库时间戳仍存 timezone-aware UTC，不使用模型运行环境时区替代业务时区。
3. 拆出材料检查：年度盈亏表至少一份、流转表唯一、同年重复文件拒绝、文件 role 与 owner/department 匹配、历史无年份兼容仅走旧规则，不在重构时擅自重分配年份。[S20]
4. 取数连接器只负责只读获取与校验，凭据通过既有受控通道取得；context、result、异常和日志不得出现账号密码。
5. 正式取数、快照回放两种来源保留。回放必须验证 scope、格式版本、完整性、日期覆盖；生产保持原有关闭/开启策略，不自动开启开发回放。
6. 取数包是原始可重放材料，预览是派生索引。原始包清理后预览可保留，但不得伪装成可回放包。
7. 补取必须绑定原取数来源和会话版本。快照模式不允许偷偷补调用真实智云。
8. 预览接口保留分页、搜索、脱敏和计数口径。禁止对每次翻页读取全部历史 JSON，禁止解析失败回退完整原始数据。
9. 确认取数绑定当前 preview/bundle revision；确认之前有补取或刷新产生新版本时，旧确认不能自动继承。
10. 任务提醒仍只负责告知/预填，不自动创建财务执行，不与正式任务混在幂等键命名空间。
11. 迁移旧 facade 中的 `_load/_json` 等辅助函数前区分其异常容错语义，不能统一成“解析失败返回空”而掩盖关键材料缺失。

### 测试

缺少某取数文件、返回记录数不一致、跨年材料、空业务日期、有付款无订单、回放包损坏、原始包被清理仅剩预览、跨用户选包、补取版本变化、确认后材料改变、日期列表排序。

### 验收

取数的数据内容、计数、展示分页、材料绑定和审批提示与原基线一致；新模块不直接修改 workbook；原错误场景仍能说明缺哪份材料或哪个阶段。

### 回滚

旧 API 委托回原用例读取同一版本材料；已创建任务保持原取数来源，不重新抓取/重新初始化已有固定 bundle。

<a id="pr-10"></a>

## 6.12 PR-10：拆核销判定、证据与计划，保留 14 个阶段

### 当前执行契约

固定提交的 `ar_execution_contract.py` 声明 `ar-execution-v2`，且阶段完成记录必须是合法连续前缀。[S19]

| 顺序 | 现有 phase 名 | 目标模块 | 必须保留的含义 |
| --- | --- | --- | --- |
| 1 | `inspect_materials` | application/inspect_materials | 检查本次固定材料 |
| 2 | `classify_receipts` | application/classify_receipts | 首次确定性判定 |
| 3 | `review_order_evidence` | application/review_evidence | 逐单证据覆盖 |
| 4 | `validate_reconciliation` | application/validate_plan | 校验计划与 guard 字段 |
| 5 | `build_initial_report` | application/build_reports | 首次日清 |
| 6 | `stage_reconciliation` | application/stage_write | 建立隔离暂存 |
| 7 | `write_ledger` | application/apply_ledger | 盈亏写入与回读 |
| 8 | `write_receipt_flow` | application/apply_receipt_flow | 登记/回填流转 |
| 9 | `verify_reconciliation` | application/verify_write | 写后业务复核 |
| 10 | `rescan_holds` | application/rescan_holds | 重扫挂账 |
| 11 | `build_final_report` | application/build_reports | 最终日清 |
| 12 | `review_final_report` | application/review_final_report | 最终清单与原因核对 |
| 13 | `publish_reconciliation` | application/publish_materials | 发布已复核材料 |
| 14 | `complete_reconciliation` | application/complete_execution | 发布核对与正式台账登记 |

不把 14 个 phase 各自做成一个微服务或数据库队列。可以按职责合并源文件，但持久化阶段名、顺序和校验保留。

### 实施步骤

1. 迁移 `next_phase/require_phase`，测试空前缀、合法前缀、重复步骤、跳步骤、乱序、未知步骤、完成后继续请求。
2. 生成计划仍调用任务固定的 Skill 脚本。模型可辅助解释证据，不直接把模型自由文本转为 workbook 写入。
3. 证据必须覆盖要求检查的订单/回款集合。分页读完、证据成立、计划可写是不同状态，不能把“模型看过第一页”视为全部覆盖。
4. 保留 `plan_fingerprint`、业务日期、material_set_id、material_version 等写入 guard，明确它们的生成源和更新时机。
5. 将首次报告、最终报告、范围报告的区别写入返回协议，不合并为同一个“生成报告”并丢失恢复边界。
6. 保留挂账、跨期、历史核销、空日、延期复核等既有策略；只能重排代码，不擅自使用新的财务判断。
7. 对确定性普通 runner 与 Agent/Harness 共用同一 phase 校验服务；Agent 工具白名单从固定契约生成/验证，不维护一份可漂移副本。
8. 不新增无实际状态依据的确认/审批卡片。审批链有无及需要哪些确认仍由现有实际执行契约决定。
9. 对每个阶段记录输入引用、输出摘要、代码版本、状态变化和错误；日志只留脱敏摘要，不为观测扩大模型数据可见性。

### 验收

固定输入下计划明细、金额、币种、期间和业务状态一致；非法阶段不能调用；合法旧 v2 记录可继续解析；Agent 不能跳过核验。

### 回滚

只回退代码组织，不修改已完成阶段数组。不得把失败执行的 completed 清空后重新开始。

<a id="pr-11"></a>

## 6.13 PR-11：拆暂存、写入和写后校验

### 修改位置

`ar_execution_runner.py`、`workflow_service.py` 的写入和异常分支、`ar_write_inspection.py`、`ar_process_evidence.py`、`ar_staging_archive.py`、`ar_staging_retention.py`、`run_fencing.py` 相关成果登记。

### 明确三个对象

`原始材料`：不可修改；`本次工作副本/暂存副本`：本任务写入；`正式发布材料`：完成校验后登记的新版本。

不得为了少复制一次文件，直接让子进程写原始上传路径；不能将可写目录共享给并发用户或不同 attempt。

### 具体步骤

1. stage 前检查当前有效租约、授权、固定材料、合法阶段和 plan_fingerprint。
2. 创建与 task/action/attempt 绑定的唯一暂存目录，保持既有目录兼容和证据格式。
3. 写前记录输入文件 hash、预计修改范围、脚本版本、命令摘要、调用 ID、材料版本；敏感参数按既有策略保护。
4. 执行脚本前释放不必要长事务锁，但保留能重新验证的阶段 checkpoint。不能持数据库全局锁等待整个 Excel 或浏览器过程。
5. 写入脚本只能访问声明的工作文件和输出目录。普通固定工具也逐步复用这一保护，不能把有全数据卷权限的 Worker 误认为每任务强沙箱。
6. 进程执行保留 timeout、stdout/stderr 脱敏、process identity、process_exit_confirmed、退出码和证据关联。返回码为 0 不等于所有业务校验通过。
7. `write_ledger`、`write_receipt_flow` 分别保存阶段结果，不能因为后者失败而重跑前者；确切恢复动作仍由原政策与证据决定。
8. 写后重新读取受控文件检查金额、明细、公式和计划覆盖，使用固定脚本/校验逻辑；不要把模型评价当回读校验。
9. 进入正式发布前再次核验文件内容、材料 lineage 和执行资格，防 worker 在副本完成后已经失去资格。
10. 在任一不确定边界，记录 `write_status=unknown/applied_unverified` 等内部语义，映射到现有可兼容错误响应；不自动归类为未写入。
11. 取消在安全检查点生效；执行器未确认退出时保持 cancelling/outcome unknown。不要直接标 cancelled 并放开同一文件写入。
12. 临时目录清理延后到完整结果/证据归档且无活跃引用。清理错误不能把财务任务重排，也不能删除需要恢复的暂存。

### 故障注入点

stage 完成未执行、第一张 workbook 写完、第二张 workbook 写一半、脚本退出后 DB 断连、回读失败、租约过期、用户撤权、取消与发布同时发生、磁盘满、文件被外部修改。

### 验收

原材料保持不变；旧 Worker 只能留下不能发布的孤儿副本；对每个注入点能说明是否已写、哪里可恢复、为何不会重复执行；同一材料版本的并发发布会受阻。

### 回滚

先暂停目标业务接新任务并确认活动动作；只回退代码不能撤销已经写完的副本或正式材料。保留阶段证据按恢复矩阵处理，不清空工作目录。

<a id="pr-12"></a>

## 6.14 PR-12：拆发布、批次、恢复，收尾巨型 service

### 修改位置

`workflow_material_service.py`、`ar_publication.py`、`ar_formal_ledger_service.py`、`ar_execution_recovery.py`、`ar_report_recovery.py`、`ar_recovery_adoption.py`、`workflow_service.py` 中 `_fail_batch`、批次协调和终态处理。

这些路径在已读代码中被引用；实施时必须完整阅读具体实现，不能依据文件名假设内部已经符合以下要求。

### 发布实施

1. 定义 `PublicationRequest`：scope、workflow/action/attempt、父材料版本、计划 fingerprint、固定 Skill revision、已校验成果清单、必要确认/审批引用。
2. 复用现有材料 version/current 约束、publish 函数和恢复证据，不新增同义“ledger_versions”表。
3. 大文件归档先落到不可变目标；通过内容校验后再在短 DB 事务中登记 FileRecord、材料成员、新 current、关联和审计。
4. 文件系统与 DB 无跨介质原子事务。明确“文件落地但 DB 未提交”作为可检查孤儿；“DB 已提交但应答丢失”通过发布操作 ID/原 workflow 关联回查，不能再发新版本。
5. 发布前持有既有正确范围的材料锁/CAS；在同一事务中校验当前父版本并提交后继版本。同一作用域并发首次创建也必须有唯一约束或确定的作用域锁。
6. 数据库约束冲突转换为 `MATERIAL_VERSION_CONFLICT`，不能异常后改用新父版本静默重试。
7. “已 verified 但未完成 formal_ledgers 登记”保留为待完成登记状态；根据现有 `publication_needs_completion` 恢复，不重新写 workbook。[S19]
8. 财务成功与范围报告成功分开。每日核销已成功、范围报告失败时，保留成功日结果，恢复只生成报告。

### 批次实施

- 固定首日 Skill 契约；后续日期即使尚未复制本日快照，也必须按首日固定版本校验。
- 前一日材料发布和必要回读完成后，下一日才绑定该材料版本；不能提前取“全局最新”。
- 多日期共享 bundle 只共享取数，不合并为跨日写入计划。
- 失败日期后的子任务保持暂停，不产生下一日财务副作用。
- 用户重试批次必须识别已成功日期，继续失败日期的允许阶段；不能重新创建一批把成功日再次执行。
- 合法历史恢复生成新材料版本，记录 lineage，不把旧版本 state 强改 current。

### 恢复矩阵

| 已知事实 | 允许的默认动作 | 禁止动作 |
| --- | --- | --- |
| 准备失败，确认无写入 | 修复输入后重建/重试准备 | 自动修改固定材料/执行模式 |
| 暂存存在，未开始脚本，进程已确认退出 | 按既有政策清理或重建暂存 | 删除原材料 |
| 脚本状态未知或退出未确认 | 调查进程与证据 | 直接重跑写入 |
| 第一阶段已写、后续未完成 | 按阶段证据恢复 | 从第一写入步骤重跑 |
| 已写入但回读失败 | 恢复回读/校验 | 再次应用同一写入计划 |
| 材料已发布但登记未完成 | 补齐登记与审计 | 创建第二份正式发布 |
| 每日完成但范围报告失败 | 仅恢复范围报告 | 重跑全部日期 |
| 旧 Worker 尝试完成 | 拒绝该代次发布 | 覆写现有完成结果 |
| 历史 JSON 无法可靠解释 | 管理员调查，保持保护 | 按空记录处理或删除 |

### 结束 service 拆分

完成后 `workflow_service.py` 只保留兼容导出和尚未迁移的非 AR 内容，逐一列明原因。所有迁移函数只能有一个实现；存在临时 wrapper 时有调用者清单、退役条件，不用行数指标强迫删除必要兼容。

### 测试与回滚

全量合成核销回归、逐阶段故障、并发发布、历史版本恢复、批次中断续行、scope 变更、权限/审批变化、旧 v2 快照读取。代码回退保留新材料与操作回执，不 downgrade 删除历史。

<a id="pr-13"></a>

## 6.15 PR-13：Pi 命令、运行时关联与控制协议

### 修改位置

`routers/pi_runtime.py`、`pi_runtime_service.py`、`pi_skill_bindings.py`、`pi_business_access.py`、`pi_model_access.py`、`deployment/pi_runtime_manager.py`、`deployment/native_agent_jobs.py`、现有 agent-runtime 相关代码。

后两项具体实现必须在 PR-00 完整读取并定位真实动作分发函数；不得仅凭文件名照搬修改。

### 先完成路径决策

核对旧 Native、新 Pi workspace、AI chat、Agent/Harness 的实际调用：固定工具触发、自由命令、后台 jobs、对话内同步工具调用分别走哪里。**默认保留新 Pi 与 Harness，不新增第三套 jobs。**

### 协议实施

1. 为对运行时具有副作用的操作增加稳定 `command_id/request_id` 与协议版本；UI 网络重试不得重复生成 ID。
2. start/send/job.submit/upload_commit 等分别定义重放含义。send 若会触发模型/工具执行，也必须有重复投递保护。
3. 运行时管理器持久记录命令接收与执行关联，保证同 scope/session/command 的重放返回原 receipt。平台幂等表只登记平台请求，不能代替运行时自身去重。
4. API 调用 UDS 超时后先按 command ID 查询运行时。查询未确认不等于没收到，禁止自动换新 ID 重发。
5. 长任务由已有 jobs 接口承载，返回稳定 job ID；短命令仍可保留同步响应，但同样要有回执与去重，不能统一改超时时间掩盖后台执行。
6. 平台新增关联记录时绑定 owner、department、session、runtime、command、job，约束唯一组合；后台状态仍由运行时负责，平台只保存最后观察。
7. 事件协议包含 source、scope、execution_ref、sequence、schema_version、timestamp、type。sequence 使用运行时原序号或稳定接收索引；不能用客户端当前时间代替去重键。
8. 状态轮询支持 cursor/from_sequence，重复与乱序事件可合并。终态不得被晚到 running 覆盖，重新执行必须新代次/新 command。
9. 会话停止和 job 取消必须作用于自己对象。撤权后保留合法 stop/cancel，不允许借此运行新命令。
10. 允许使用用户拥有的固定 Skill 包，必须保持不可变包版本；新 Pi 所依赖的 native 包管理继续保留。
11. manager 的 UDS 协议验证 peer/owner、payload 类型、长度、白名单操作、路径；API 不可提交任意 docker 参数、host path、环境变量或 root 命令。
12. systemd root manager 即使必要，也仅接受窄协议，目录权限与 socket 权限正确；不将 Docker socket 挂到模型环境。
13. 文件目录索引第一轮保留单机限制。JSON 更新必须原子写、锁范围明确；不得声称此方案已支持多主机。数据库会话化作为后续显式任务，不在此 PR 混入目录重建。
14. 文件上传的 begin/chunk/commit/abort 保留完整性、版本、配额与归属；commit 重放不能重复登记或覆盖其他会话文件。

### 测试

重复 submit/send、提交应答丢失、运行时重启、平台重启、事件重复/乱序、跨用户会话、权限撤销、挂载记录应答丢失、job cancel 重放、上传中断/重复 commit、未知版本协议。

### 验收与回滚

关闭浏览器不会丢失后台任务查询；超时回查能关联原命令；旧历史记录可读；旧端暂不支持 command 去重时不能盲目自动重发。回滚保留命令回执，不清空 runtime 工作目录。

<a id="pr-14"></a>

## 6.16 PR-14：正式文件成果与任务查询统一

### 修改位置

`storage.py`、`file_service.py`、`resource_policy.py`、`models.FileRecord/ArtifactBinding`、`task_center_service.py`、`workbench_service.py`、Pi files/download 路由及成果组件。

### 正式成果登记

1. 区分输入、临时产物、已归档成果和正式业务材料；复用现有 kind/业务关联，必要字段增量扩展。
2. 设计 `register_artifact(scope, source_execution, immutable_source, role, expected_hash)`；内部复制/流式读取允许范围文件、校验 hash/大小/类型、登记 FileRecord 和来源。
3. 跨数据库和 runtime 文件系统通过明确“准备—复制—校验—登记”协议，不能将 manager 内路径直接信任为下载路径。
4. 同一 source_execution、逻辑产物 key、版本/内容重复登记返回原引用；内容变了则生成新版本或拒绝冲突，不能覆盖历史 FileRecord。
5. 临时命令输出不强制全部登记，否则会堆积海量中间文件；用户选择“保存为成果”或业务发布时登记。实际财务必要证据不能因未点保存而丢失。
6. 上传与复制必须校验文件实际类型、大小、路径和引用；禁止对同 hash 跨 owner 直接复用授权。物理去重可以后续单独设计。
7. Markdown/HTML/Excel 预览禁止执行宏、公式外联或主动内容。已有合法 Excel 公式原样保留，不为“安全处理”破坏业务公式；新外部文本导出另按既有防公式注入策略处理。
8. 大文件 hash/复制采用流式处理；不要一次性载入数 GB，保留断点和配额限制。

### 引用与删除

1. 继续使用已有 ArtifactBinding、WorkflowMaterialSetFile 等关系；新的 Pi 引用用最小必要绑定表达。
2. 删除保护与文件详情共用 `reference_service`，不能一个用新索引一个仍解析旧 JSON。
3. 新记录同步登记引用；历史 JSON 回填按 keyset 分批，处理可解析/不可解析/缺失引用三种结果。
4. 回填前后双读比较，只读影子比对允许，影子业务写入禁止。
5. 历史 JSON 解析失败或引用未知按“仍需保护”处理，不能因为新表没记录就允许删除。
6. 删除前锁文件/引用或通过软删状态阻止新绑定；仅先 count 再删除存在竞态，需要事务复查与并发测试。
7. 物理删除有独立保留期和明确证据，先 tombstone 后异步清理；失败可重试物理清理，但不重跑财务任务。

### 查询统一

1. 扩展已有任务中心投影，保留普通 run、独立日期、batch 各自去重逻辑；Pi 会话与其命令不能全部无差别累加成财务任务总数。
2. 展示任务分类、底层状态、观察时间、可用操作。映射函数集中在服务端/共享合约；前端不从中文 message 猜状态。
3. 查询必须先加 owner/department/管理员范围，再做聚合、分页、统计。缓存 key 包含身份作用域。
4. 跨来源分页使用稳定 `(created_at, kind, id)` 游标或数据库投影；不能每个来源各拿一页后拼起来假称是全局正确分页。
5. 保留历史路由和深链；新 ID 包装不能破坏旧文件下载和任务详情。

### 验收

同一任务各页状态一致；批次无重复计数；成果可追溯到固定 Skill 和命令；跨用户 404/403 符合原策略；历史未知引用文件不能删除；query 成本不随全部历史 JSON线性增长。

### 回滚

新增引用继续保留，查询可暂回旧投影；删索引/删表不能作为快速回滚。物理文件删除不可逆，因此此 PR 默认不授权删除真实历史文件。

<a id="pr-15"></a>

## 6.17 PR-15：统一 SkillRevision 与发布协议

### 修改位置

`registry.py`、`skill_source_service.py`、`skill_install_service.py`、`native_skill_service.py` 中安装与包管理、`skill_rollout_service.py`、`skill_availability_service.py`、`routers/admin_skills.py`、`deployment/deploy_platform.py`、`deployment/deploy_tool.py`、`scripts/sync_finance_skills.py`。

具体旧函数调用与所有副作用在 PR-00/当前任务阅读后补齐 source-map；不能因为存在同名 source/rollout 就假设已经共用状态。

### 版本身份

一个版本至少记录：逻辑 Skill ID、来源类型、来源仓库与固定 commit、源码子路径、包内容 SHA-256、manifest schema/业务执行契约版本、展示 version、依赖锁或运行镜像 digest、发布审批/来源、安装时间。展示版本号不能代替内容 hash。

固定工具与原生 Skill 继续分开管理，增加明确 `skill_kind`；同样业务名称不自动合并 ID 或权限。运行时包可以共享不可变版本基础，UI 和执行政策保持区别。

### 实施步骤

1. 审查现有 SourceBinding/SourceRevision/Rollout 等模型，优先扩展，不再新建意义重叠的 SkillRelease 表。
2. 为固定工具、Native 包、Pi 绑定建立统一版本引用适配器；保存原 commit/hash/source path，不丢上游来源。
3. 已有按任务复制的 snapshot 第一轮保留。后续内容寻址去重必须验证只读挂载、依赖和历史回收，不能此次为省磁盘把历史快照删掉改读最新包。
4. 同步只负责发现候选/生成审查包，不自动把远程 main 作为生产执行版本。原有定时同步可能重启服务的行为必须盘点，不能与统一发布同时抢写。
5. Web 与 CLI 提交同一种发布请求，包含 expected 当前版本、目标 revision、操作者、generation、检查结果、回滚材料引用。
6. 第一轮保留现有目标 Skill 排空政策，包括排队、运行和必要确认中的任务；不为了免等待而取消任务、改状态或跳过审批。
7. 发布获取排他锁和目标 Skill 可用状态代次，暂停只影响目标，不误停全站。管理员原已暂停的工具不自动启用。
8. 安装暂存包，校验 hash/manifest/依赖/执行契约/安全扫描后切换。系统依赖或 runtime 合约变化走完整服务发布，不能伪装成脚本-only 热更新。
9. 对 API、Worker、提醒 Worker、Pi 包索引的版本观察建立核对，不把 `registry.refresh()` 只在一个进程执行就认为全平台更新。
10. 恢复接单前检查当前 pause 所有权、generation、目标版本；管理员或后续发布已变更状态时停止自动覆盖。
11. 同步回滚启动镜像/包指针与运行副本，不能只有当前容器正确而重启回到旧代码。
12. 发布日志不记录明文 env；rollback package 权限受限，不上传 CI artifact。
13. 发布操作断电/强杀后，通过 release receipt、当前版本、容器身份、hash、pause generation 进行可验证恢复。不能无限重试 install。
14. release 状态需要区分 completed、failed、recovery_required。失败不自动重新执行任何财务任务。

### 最小发布状态机

```text
prepared → validated → draining → installing → verifying → completed
                 │          │           │            │
                 └──────────┴───────────┴────────────┴→ failed / recovery_required
```

此状态机描述发布操作，不替换财务任务状态机。启用目标工具是有条件的最后操作，不能写在无条件 finally 中。

### 测试

两入口并发发布同工具、不同工具、工具原先暂停、等待排空超时、目标版本变动、安装失败、hash不一致、部分副本更新、管理员同时修改状态、进程强杀、成功日志写失败、提醒 Worker 保留旧导入。

### 验收与回滚

同一版本身份跨入口一致；只影响目标工具；新任务使用批准版本；在途任务固定契约不变。回滚只在操作所有权仍有效时执行，不能覆盖后来管理员操作。

<a id="pr-16"></a>

## 6.18 PR-16：前端共用、BFF 与任务交互

### 修改位置

`web/src/config/platform-navigation.ts`、`nav-config.ts`、`features/platform-api/`、`features/runs/`、`task-center/`、`files/`、`workflows/`、`workflow-agent/`、`ai-chat/`、`pi-runtime/`、`run-setup/`、相关 App Router 页面和 BFF。

### 页面组织

保留当前七个员工入口的职责：工作台、工具中心、Skill 中心、Pi 工作区、我的任务、文件中心、AI 助手。可以调整文案、分组和共用组件，但不能把工具中心和原生 Skill 中心不加区分地合并。[S26]

`Pi 工作区` 可保留高级文件/环境交互，`AI 助手` 承担普通自然语言入口；共享会话消息组件不代表共享同一种可写业务状态。

### 实施步骤

1. 先画现有页面—BFF—后端接口映射，逐条保留历史 URL、面包屑、快捷键和角色导航。
2. 所有后端数据类型从 `contracts/financial-platform.openapi.json` 生成至 `features/platform-api/generated.ts`；稳定别名在现有 types 文件维护，不手写另一份业务 DTO。
3. OpenAPI 变更先更新后端 response_model，再运行现有 `scripts/export_openapi.py` 和前端生成脚本，最后检查 diff。[S30]
4. 提取共用 `TaskStatusBadge`、`ProgressPanel`、`FailureDetails`、`ArtifactList`、`FileSelector`、`ConfirmationPanel`、消息渲染基础组件。名称为建议，不存在同等组件时才新增。
5. 核销日期选择、取数确认、材料版本、逐单证据、批次恢复保留业务组件，不强行退回通用 JSON 表单。
6. TanStack Query key 必须区分用户/部门/资源/过滤条件；登出、账号切换、部门变化时清理相应缓存，避免渲染上一个用户数据。
7. mutation 的逻辑提交 ID 独立于 HTTP request ID；自动 retry 仅对安全 GET/明确幂等操作启用，未经去重的 POST 不自动重发。
8. 处理 202 receipt、409幂等冲突、权限撤销、租约失效、材料冲突、状态未知。UI 不根据模型最后一句“已完成”直接将任务设成功。
9. 状态同步由一个 hook 负责，每个页面生命周期明确注册/清理；避免 SSE 与轮询各自更新不同状态。流断线先从 cursor 恢复，不重新创建任务。
10. BFF 按端点明确 timeout 与流式行为；不能用一个短 timeout 截断全部长下载/SSE，也不能全局无限超时。
11. BFF 只转发允许的服务端身份与 request/idempotency header；不信任浏览器自填 owner/role；禁止把 Key/Cookie 放 URL 查询参数。
12. 敏感用户数据 `no-store` 或使用正确私有缓存；不能跨用户共享 server cache。下载 MIME、文件名编码、Content-Disposition、安全 header 保持。
13. 审批界面显示具体材料版本、计划摘要与过期状态；按钮禁用只是体验，真正判定后端完成。
14. loading、空列表、失败、部分成果、后台运行、可恢复状态分别展示；不要用一个通用“出错了重试”诱导重复写入。
15. 未完成 TaskDraft 与正式 Run 区分；聊天消息只是建议时不能生成假成功任务卡片。
16. 保留主题 token 和现有组件体系；移除样式重复前检查 CSS import、类名动态使用和可访问性。不要混入整套新 UI 框架。
17. 固定布局与专用页共享无业务组件，禁止相互 import 巨型页面来复用一小块展示。

### 测试

原有 navigation、run-access、platform-data、agent-wire、hydration 测试全部继续执行；新增重复点击、浏览器刷新、SSE 重连、跨账号缓存、深链、202/409、权限撤销、批次恢复、文件下载中断的交互测试。

### 完成标准

页面显示真实后端状态；所有旧路由有兼容或明确迁移；前端无重复业务 DTO；权限/缓存/幂等不依赖浏览器假设；生产 build 与类型检查通过。

### 回滚

旧前端只能与兼容后端组合发布；后端新增数据保持可读。不得仅回滚到旧前端后重新生成每次提交 key 导致重复任务。

<a id="pr-17"></a>

## 6.19 PR-17：完整构建、部署归一与运行管理器归位

### 修改位置

`deploy/docker/Dockerfile`、`deploy/production/compose.yaml`、`deploy/development/`、`deployment/Dockerfile.*`、`deployment/compose.pi-runtime.yaml`、`deployment/financial-pi-runtime.service`、`deployment/financial-native-sandbox.service`、宿主机 manager 源码、`web/Dockerfile.*`、启动/备份/发布脚本。

### 构建实施

1. 记录当前所有活跃镜像 digest、构建上下文、来源 Dockerfile、依赖与覆盖层；只从配置和经授权运行信息获取，不打印 secrets。
2. 建立少量正式完整构建入口：backend/worker、web、agent runtime、必要 Pi runtime/egress。API 与 Worker 可以共用镜像，但职责与权限配置不同。
3. 正式 Dockerfile 从明确基础镜像及固定依赖构建，不依赖某台机器才有的 `pi-context-base-日期` 等历史镜像。[S24]
4. Python 当前依赖多为范围声明，先解析并验证现有可用版本，再提交受控制的 lock/constraints 和 hash。不要同时升级所有依赖；锁文件生成工具版本也固定。
5. Node 保留现有 pnpm lock 和 packageManager；生产安装 frozen lockfile。根/子 workspace 路径和 `file:../agent-runtime` 依赖必须在完整构建上下文可用。
6. image 标注源码 commit、build id、依赖锁摘要；发布记录保存 digest。不要声称有时间戳和外部构建因素的镜像一定字节级相同，要求的是依赖可追溯与行为可复现。
7. 构建上下文 `.dockerignore` 排除 `.env`、真实 data、凭据、浏览器 profile、回滚 env 包、临时财务文件、.venv、node_modules 和历史生成输出。
8. 无网络部署使用提前批准的 wheel/镜像/npm 缓存包；不得为方便安装临时放开生产公网。
9. 依赖变更才触发相应镜像重建；开发热更新不重建全部镜像。Worker 代码变化仍按现有安全排空/重启策略，不因文件保存自动中断核销。

### manager 归位

1. 将真正长期运行的 manager/sandbox/job 管理源码从 `deployment/` 迁入 `runtime-manager/`，安装和 systemd 文件仍放 deploy。
2. 原路径在过渡期保留显式启动 wrapper；systemd 指向固定安装位置/受控 current 链接，不指向个人 releases 下任意历史目录。
3. 把 `PI_RUNTIME_ROOT`、`PI_CONTROL_ROOT`、`PI_MANAGER_SOCKET`、运行镜像、允许 UID 等参数从源码硬编码移到受控配置。root-owned 安装配置不能被普通 API 用户修改。
4. 保留 runtime、model broker、egress 的网络与凭据隔离；不会因合并目录而合并安全进程。
5. 保留 non-root runtime、read_only、cap_drop、no-new-privileges、pids/memory、tmpfs、只读包挂载、允许的工作目录、服务停止宽限期。
6. API 不额外获得 Docker socket、宿主根目录或所有人工作区。专用管理进程的接口严格白名单与 peer 校验。
7. 活跃 runtime 与 manager 协议版本必须兼容；升级 manager 不能导致未知工作目录被自动清空，旧 job 的状态可回查。
8. 备份除了 DB，还包括不可变文件、Skill 包、Pi catalog/必要工作目录、发布记录和密钥恢复方案；密钥单独加密保管，不能丢失后声称 DB 备份足够。

### 验收

在干净隔离机器/CI 构建所有必需镜像并跑 smoke；停机再启动版本不退回旧镜像；systemd无个人发布目录硬依赖；开发模式不读取生产数据；网络/沙箱负向测试通过。

### 回滚

保留旧镜像 digest、配置与 manager wrapper；旧新协议经过兼容矩阵确认。回退前排空需要停止的任务；不能使用 `docker compose down -v` 回滚。

<a id="pr-18"></a>

## 6.20 PR-18：有证据地退役旧 Native 与 legacy

### 修改位置

`native_skill_service.execute_command/reap_abandoned_runs/session_runs`、`routers/assistant.py` 中 Native API、`main.py` recovery loop、`AGENT_RUNTIME_FALLBACK` 相关实际分支、旧前端调用者、相应部署服务。

### 四阶段退役

1. **可观察**：为旧入口增加脱敏调用计数和来源标记，不改变行为。区分历史查询、安装与新命令请求。
2. **禁止新建**：满足功能覆盖后，只对新执行关闭旧入口；既有活动命令继续运行，历史读取、安装和包引用不受影响。
3. **只读兼容**：新入口接管提交，旧 API 返回明确可识别迁移错误或安全只读状态，不默默换执行器。未适配客户端不能收到假成功。
4. **删除执行实现**：调用图无活跃 writer、观测窗口覆盖实际使用周期、无活动执行、历史读取测试通过、回退包已验证后，才删除旧执行和专属进程。

### 不能顺带删除

`native-skills/packages`、`installed`、固定会话快照、旧结果文件、Native 权限 ID、仍供新 Pi 挂载的安装服务、必要历史 reaper/恢复逻辑。manager、Pi workspace、Harness 的名字相似不能证明可替代。

### 决策缺证据时的默认行为

保留旧路径并标 `blocked_for_removal`，完成新路径/观测改造；不要卡住所有其他 PR，也不要虚构“零调用”。没有线上数据时交付采集方法和关闭开关，不执行删除。

### 验收与回滚

旧链接可查询/下载，未覆盖功能不会消失；新旧路径不会对同一 command 双执行。回滚仅重新允许经验证的旧提交入口，不能将已在新 runtime 执行的命令重投旧执行器。

<a id="pr-19"></a>

## 6.21 PR-19：观测、资源限制、故障与性能基准

### 修改位置

`runtime_health_service.py`、`task_errors.py`、日志/审计服务、Worker 调度、模型连接调用、发布状态、前端错误呈现；新增隔离压测与故障注入测试。

### 观测实施

1. 日志链贯穿 request_id、idempotency receipt、execution_ref、action/attempt、Skill revision、release id、artifact id。用户 ID等不作为高基数 metrics label。
2. 测量 queue wait、claim latency、执行耗时、lease loss、retry denied、outcome unknown、材料冲突、发布恢复、Pi sync lag、文件归档失败。
3. 日志分员工摘要/管理员细节；所有输出先按现有脱敏策略处理。异常 response body 与 UDS raw payload 不能原样 dump。
4. 模型调用观测记录 provider/model、用途、耗时、token、失败码、关联执行；不默认为审计需要就保存所有原文财务数据。
5. liveness 不依赖所有外部服务，readiness检查该服务实际必要依赖；管理员健康页才展示详细队列、版本和错误，不扩大匿名信息面。
6. API/Worker/manager 每个服务设置资源限制、请求/命令大小、超时、上传配额；默认值应由现有配置与基线测量确定，不在此文假装知道机器容量。
7. heartbeat 异常不能被长期完全吞没，应有节流日志/指标；避免每次轮询产生大量重复错误。
8. 维护任务日志说明回收对象、依据与结果；无引用判定失败只记录并跳过，不自动强删。

### 基准方法

使用同一组合成数据、相同并发、同一资源配置，对比 before/after 的 p50/p95、队列公平性、SQL 次数、锁等待、峰值内存、文件 IO 和镜像启动行为。

建议回归门槛作为初始工程目标：无新增安全失败；无持续饥饿；关键接口 p95 不超过可解释基线的 1.2 倍；结果登记/权限查询 SQL 次数受分页上限约束。该 1.2 是待项目采纳的比较阈值，不是线上现有 SLA；达不到时提交测量和原因，不能人为调测试数据掩盖。

### 故障演练

至少覆盖 API crash、Worker crash、manager crash、DB 中断、磁盘满、SSE断线、模型超时、租约失效、Skill 发布中断、文件归档中断及跨用户访问。每次演练能从日志重建“执行到了哪里、是否写入、谁仍有资格、下一安全动作”。

### 验收与回滚

关键失败有可追溯事件，告警不含敏感数据；观测系统失效不能放开安全闸。回滚观测采集不删除必须审计的业务事实。

<a id="pr-20"></a>

## 6.22 PR-20：清理重复代码、依赖和文档

### 修改位置

PR-00 生成的 duplicate/source/deletion 清单；`sources`、`skills`、`standalone-skills`、`native-skill-overrides`、`web` 中历史模板、`deployment` 补丁文件、各 README/CONTEXT/ARCHITECTURE 文档。

### 清理步骤

1. 对每个候选标注类别：完全重复实现、同职责不同实现、生成产物、vendor来源、历史兼容、产品功能重叠。不同类别的删除规则不同。
2. 完全重复逻辑抽到正确模块，通过原签名 facade 委托；对财务算法重复先对比业务语义，不能合并不同期间/币种策略。
3. 为 vendor/source 副本选唯一维护源和可重复构建方法，保留 upstream revision、license、patch/override 清单。生成包不能手工改后不回源。
4. 移出活动构建的旧 Dockerfile/试点启动器必须满足 PR-17重建与回滚要求；Git 历史可保存源码，正式回滚材料按保留策略保存。
5. Clerk 依赖只有在所有支持部署不再使用且明确取消支持时才删。默认本轮保留认证 adapter，不因生产 Compose 写 session 就认定其它环境不需要。
6. 前端依赖检查要包括动态 import、CSS、构建配置、服务端代码、peer dependency；工具报告 unused 后还要 build/交互测试，不按名称删 kbar/cmdk、AI SDK、xterm。
7. 禁用 Skill 默认保持不可执行/实验状态，不删除其说明与历史关联。`task-clarifier/env-doctor` 不强行成为普通财务任务。
8. 技术文档只保留一份当前架构；Skill 数量/状态从注册表导出，环境模式从实际配置说明。历史“下一阶段要接 PostgreSQL”等旧计划移入历史，不与当前事实混写。
9. `AGENTS.md` 更新真实命令、架构边界、禁止生产动作和新增测试；不能写“测试都通过”这种会过期的断言。
10. 删除前执行全仓引用、构建、部署脚本、历史 API、fixture 和迁移检查。迁移文件和历史协议解释器原则上不作为普通 unused 清理对象。

### 验收

deletion-ledger 每条都有依据/替代/历史策略/测试/审批状态；所有已删功能有覆盖或明确批准取消；没有将 source 与 build 输出一起删掉造成无法重建。

### 回滚

普通源码恢复自 Git；已删除部署/数据不保证靠 Git恢复，因此本 PR 不主动清除真实数据和回滚材料。锁文件回退与 package.json 同步。

<a id="pr-21"></a>

## 6.23 PR-21：综合验收与发布交付

### 交付内容

1. 完整源代码改造及新旧映射。
2. 每个 PR 的真实测试报告、失败清单与未验证项。
3. Alembic 迁移、历史回填、dry-run与回退说明。
4. 合约快照、生成客户端、历史 API 兼容矩阵。
5. 正式完整构建、镜像/依赖/源码版本清单。
6. 生产发布 runbook、灰度/回滚/故障恢复步骤。
7. deletion-ledger 与尚未获准删除对象。
8. 最终 progress、风险、后续可选优化，不能留隐含 TODO。

### 综合验收

按第 9～14 章逐项签收。所有 P0 用例通过、没有未解释的财务差异、数据迁移可重复、真实生产操作未越权、每种回退不重复财务写入。

用户未授权生产时，本 PR 输出可执行发布包和前置检查，不实际迁移/重启。明确报告“代码与隔离测试完成；生产未执行”，不能宣称“已上线”。

### 完成定义

不是目录看起来更整齐，而是以下事实成立：一个逻辑提交不会重复创建有效执行；当前权限控制新危险动作；旧 Worker 不会发布；每次财务写入可回查；核销核心依赖单向；版本与发布可追溯；历史任务与文件不丢；新旧路径去留有证据。

<a id="chapter-7"></a>

# 7. 接口契约与实现补充

## 7.1 对外兼容原则

第一轮不整体升级为 `/api/v2`，也不更换所有现有 URL。新增能力可以有明确新端点，旧端点保持旧响应形状直到调用者完成适配。

每次接口修改同时提交：后端 request/response schema、权限说明、错误码、幂等语义、OpenAPI diff、BFF透传、前端类型、正向与反向测试。

不得依赖“TypeScript 编译没报错”证明后端鉴权、错误码或流式行为兼容。

## 7.2 提交回执

以下是**建议新增的公共契约示例**，不是声称现有接口返回它：

```json
{
  "schema_version": "submission-v1",
  "request_id": "a-request-uuid",
  "receipt_id": "an-idempotency-record-uuid",
  "submission_state": "bound",
  "execution": {
    "kind": "run",
    "id": "a-run-uuid"
  },
  "replayed": false,
  "status_url": "/api/submissions/an-idempotency-record-uuid"
}
```

如果新增 `/api/submissions/{receipt_id}`：仅 owner/department 或已授权管理员可查询，receipt UUID 不是 bearer token。准备中 execution 为 null，不能返回伪造任务 ID。只读查询不调用 LLM，不触发财务执行。

重复提交不缓存动态授权结果；用户失去读权限后，不能凭旧 receipt 获取结果内容。

## 7.3 执行详情公共头

```json
{
  "schema_version": "execution-view-v1",
  "execution": {"kind": "pi_job", "id": "runtime-job-id"},
  "parent": {"kind": "pi_session", "id": "session-uuid"},
  "source_status": "running",
  "display_status": "running",
  "observed_at": "2026-09-18T05:40:00Z",
  "sync_state": "current",
  "available_actions": ["cancel"],
  "artifacts": []
}
```

`available_actions` 必须由当前权限与真实阶段计算；不能由前端自行推断。`sync_state=stale/unreachable` 不自动覆盖真实终态。上述状态是新查询头的设计值，不要求修改现有 DB enum。

## 7.4 错误响应

```json
{
  "error": {
    "code": "EXECUTION_OUTCOME_UNKNOWN",
    "message": "执行结果尚未确认，请查看运行记录；本次操作不会自动重新执行。",
    "request_id": "a-request-uuid",
    "retryable": false,
    "recovery_actions": ["inspect_execution"]
  }
}
```

旧 API 若使用 FastAPI `detail`，通过版本适配保持兼容；不要一次把所有错误包装改成上例。`retryable` 表示该具体动作是否允许重试，不是“HTTP 客户端可无条件重发”。

## 7.5 运行时命令信封

```json
{
  "protocol_version": "runtime-command-v1",
  "owner_scope": "server-derived-scope",
  "session_id": "a-session-uuid",
  "command_id": "a-stable-command-uuid",
  "operation": "job.submit",
  "expected_session_generation": 3,
  "payload": {
    "skill_revision_id": "a-pinned-revision-id",
    "input_refs": [],
    "arguments": {}
  }
}
```

operation 需映射到现有协议允许动作，不是允许模型自行新增。不同 runtime 保留其真实 operation 名称，适配层负责转换。强类型 `Literal`/discriminated union 替代没有语义约束的任意 dict，但迁移时保留旧协议兼容与拒绝未知字段测试。

回执要包含 command_id、accepted/replayed、job_id（如有）、state/version；失联后使用同 command_id 查询。运行时必须在产生副作用之前持久登记命令唯一性。

## 7.6 文件成果契约

正式文件对外只返回 file_id、display_name、content_type、size、业务来源、下载资源引用、允许展示的 hash；不返回宿主绝对路径、容器 mount 路径或存储密码。

素材引用写入时校验 `file_id + expected_sha256 + owner/department`；仅提供 hash 不足以授权读取。外部业务任务从 Pi 临时文件创建正式输入需要显式登记，不能直接把 runtime path 塞进 WorkflowCreate。

下载期间版本变化必须可检测。旧文件若内容可变，先复制成稳定版本再导出；不能 Content-Length 来自旧版本而分块读取新版本导致文件拼接损坏。

## 7.7 SSE / 轮询协议

- 服务端事件包含稳定 ID/序号，断线支持从最后确认 cursor 继续。
- 浏览器忽略已处理重复事件，按照执行代次/来源版本拒绝过期状态。
- heartbeat 保活与业务进度是不同事件；收到网络心跳不代表 Worker 租约有效。
- BFF不得缓存、缓冲全部流或因为默认 JSON parser破坏流式响应。
- 权限在建立流时检查；长流遇到权限变化按既有政策关闭/降权。不能终身缓存首次授权。
- 事件缺口时 GET 当前详情作恢复，不重新执行任务。
- 高频进度可合并，但终态、审批和正式成果事件不能丢失。
- 无需为重构强制引入 WebSocket。既有轮询能满足要求时保留，减少通信协议数量。

## 7.8 写入授权快照

确认/审批应绑定以下信息中业务需要的子集，不能只绑定“用户点过确认”：

```text
actor / department
workflow/action/step 标识
Skill revision 与执行契约
业务日期
material_set_id 与 version
输入文件摘要
plan_fingerprint
允许的具体操作与风险等级
审批记录版本/有效期/撤销状态
```

前端显示摘要来自该快照；后端执行前验证相同快照未过期、未被材料变动失效。重构只继承当前实际需要的确认/审批，不擅自给所有普通只读工具增加管理员审批。

<a id="chapter-8"></a>

# 8. 数据库迁移、历史回填与一致性

## 8.1 迁移阶段

严格采用扩展—兼容读写—回填—校验—切读—收缩：

| 阶段 | 行为 | 禁止 |
| --- | --- | --- |
| Expand | 新表/可空字段/安全索引 | 直接删除旧字段 |
| Compatible | 新 writer 明确写新字段，旧 reader 仍可工作 | 两个并行 writer 产生同一业务执行 |
| Backfill | 分批读取旧记录，补最小确定关联 | 解析失败就按空记录回填 |
| Verify | 比较计数、引用、业务结果、异常清单 | 仅看脚本退出码 |
| Switch | 在受控范围启用新读路径 | 全平台未验证直接切换 |
| Contract | 独立批准移除旧写/字段/兼容 | 与首次增量迁移同批执行 |

本文不要求使用 dual-write 所有业务表。需要兼容字段双写时，必须在同一事务/同一 writer 维护；不能让新旧执行器各写一次业务结果。

## 8.2 Alembic 编写规则

1. 新 revision 从实际当前 head 接出，不能根据本文猜 revision ID。
2. 不修改已在生产执行过的历史 migration；确有错误写新的修复迁移。
3. autogenerate 输出人工审查，尤其 rename 被识别为 drop/create、Text→JSONB、nullable→NOT NULL、外键和索引。
4. 新字段优先可空或有明确不触发历史误义的默认值；回填完成再加强约束。
5. 不用 `default=''` 把未知会话、未知版本伪装成存在值。
6. 大表索引按实际 PostgreSQL 版本/锁影响设计；需要 CONCURRENTLY 时使用 Alembic 合适 autocommit block 并明确无法与整个迁移保持一个事务。小规模可先普通创建，但必须说明锁预算。
7. SQLite 测试分支不支持的特性采用明确替代；PostgreSQL独有锁/部分索引/JSON行为必须PG集成测，不能被SQLite假替代。
8. ORM 模型移动不应触发表删除重建。所有模型注册进入同一 Base.metadata。
9. 限定 migration 运行账号有DDL，普通 API/Worker 使用足够且更少的权限；不要给沙箱数据库账号。
10. downgrade 对存在新数据的结构若不安全，应显式拒绝/要求空表或预检，不能 silent drop。

## 8.3 历史分析 SQL 示例

以下查询是**只读审查示例**，只能在授权数据库或脱敏副本执行，不是此文授权读取生产。

```sql
-- 查找相同作用域和 adapter 的重复非空 key。
-- Native 同会话多行可能完全正常，不得直接按结果去重删除。
SELECT owner_id, department_id, adapter, idempotency_key, COUNT(*) AS n
FROM runs
WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''
GROUP BY owner_id, department_id, adapter, idempotency_key
HAVING COUNT(*) > 1;

-- 查看旧 Native 记录的关联覆盖规模，不输出 command 原文。
SELECT state, COUNT(*) AS n
FROM runs
WHERE adapter = 'native'
GROUP BY state;

-- 核对现有材料作用域是否出现多个 current；结果应结合现有约束调查。
SELECT owner_id, department_id, skill_id, COUNT(*) AS n
FROM workflow_material_sets
WHERE state = 'current'
GROUP BY owner_id, department_id, skill_id
HAVING COUNT(*) > 1;
```

报告中的 owner 等标识按共享范围脱敏；不要把查询返回的整表数据上传。

## 8.4 回填脚本必须提供的接口

建议统一入口 `scripts/refactor/backfill.py`，以下命令是**PR实现后才可使用的目标接口**：

```text
python scripts/refactor/backfill.py native-links --dry-run --batch-size 200
python scripts/refactor/backfill.py native-links --apply --resume <checkpoint-id>
python scripts/refactor/backfill.py artifact-references --dry-run --batch-size 200
python scripts/refactor/backfill.py artifact-references --apply --resume <checkpoint-id>
python scripts/refactor/backfill.py verify --report <report-path>
```

脚本要求：

- 默认 dry-run；apply 需要明确目标、专用授权配置、预检通过。
- 配置从批准位置读取，不接受命令行明文密码，不打印数据库 URL。
- 按不可变主键/稳定游标分批，保存 watermark。不能基于会被更新的 updated_at 无限制跳行。
- 每批独立事务，单批失败可回滚；已经成功的批次重跑无重复写入。
- 检查已存在目标关联是否完全一致；不一致标冲突，不覆盖。
- 支持停止信号，在批次边界写checkpoint安全退出，不强制中断事务后假报完成。
- 异常记录只保存 ID、错误码与必要脱敏字段，不保存财务原文。
- 统计 discovered/eligible/already_done/applied/skipped/ambiguous/failed；成功总数不能包含 skipped。
- 所有未知历史结构进入人工调查清单，同时保持删除保护。
- apply 运行前后都校验引用完整性和 scope；迁移代码不调用业务执行器。

## 8.5 比对标准

DB：各来源总量、成功/失败/进行中数量、关联覆盖、唯一性、外键、scope、孤儿记录、版本 lineage。

文件：所有已登记必要文件存在且 hash一致、临时/正式分离、包版本对应、备份恢复后相同引用可解析。

业务：金额、币种、期间、核销明细、前后材料引用和已成功日期保持。

历史兼容：旧任务、旧 Native 会话、旧下载 URL、旧审批记录和错误恢复入口均可访问。

出现差异不能自动改历史账；先确定是展示投影变化、旧数据不完整、迁移错误还是原业务问题。

## 8.6 无法原子跨 DB 与文件系统的处理

采用不可变文件对象和数据库“发布指针”尽量简化恢复：

```text
1. 生成唯一暂存文件
2. 校验内容并落到稳定不可变路径
3. fsync/原子 rename（仅在实际文件系统支持且同设备）
4. DB 事务校验当前材料与执行资格
5. 登记成果/材料/事件并提交
6. 确认结果；清理无引用暂存另行进行
```

第 3 步并不让整个流程具有跨介质事务；不同文件系统不能假定 rename 原子。目标目录必须满足权限与只读保护，避免稳定文件在 DB提交后被 runtime 修改。

第 4/5 步失败：留下未发布文件，标为孤儿候选，保留恢复期。第 5 步成功应答丢失：通过稳定发布 ID回查，不再次生成新材料版本。第 6步失败：仅恢复确认或归档，不重跑财务写入。

## 8.7 恢复能力验收

至少在空环境恢复一份合成“数据库+文件+Skill包+Pi索引+密钥占位方案”的备份，证明任务详情、下载、材料 lineage 和版本校验可用。仅证明 `pg_restore` 返回 0不构成完整平台恢复。

密钥真实内容由有权人员恢复，本模型测试使用独立测试密钥。避免将生产主密钥复制到开发环境。

<a id="chapter-9"></a>

# 9. 自动化测试清单

下面全部是**待执行验收要求**。本文没有声称这些用例已通过。优先扩展现有测试文件；下列建议测试文件名先搜索是否存在，避免重复创建不同目录的同名测试。

## 9.1 建议测试归属

| 测试主题 | 建议新增/扩展文件 |
| --- | --- |
| 提交事务与幂等 | `backend/tests/test_submission_idempotency.py` |
| 事务提交边界 | `backend/tests/test_transaction_boundaries.py` |
| 撤权与启动授权 | `backend/tests/test_execution_authorization.py` |
| 租约、代次和风险 | `backend/tests/test_execution_leases.py`、`test_retry_policy.py` |
| 队列公平性 | `backend/tests/test_scheduler_fairness.py` |
| 迁移启动行为 | `backend/tests/test_schema_lifecycle.py` |
| 核销公开依赖 | `backend/tests/test_reconciliation_boundaries.py` |
| 核销阶段/发布恢复 | `backend/tests/test_reconciliation_phase_contract.py`、`test_reconciliation_recovery.py` |
| Pi重放与状态 | `backend/tests/test_pi_command_protocol.py` |
| 文件引用与归档 | `backend/tests/test_artifact_references.py` |
| 发布与版本 | `backend/tests/test_release_protocol.py` |
| PostgreSQL并发集成 | 现有根 `tests/` 或新增专用 integration 目录，按项目 fixture 统一 |
| 前端任务交互 | `web/tests/` 现有测试及新增任务/缓存/幂等测试 |

## 9.2 提交与事务测试

| ID | 场景 | 断言 |
| --- | --- | --- |
| T01 | 同key同内容顺序提交2次 | 同一执行ID，业务创建一次 |
| T02 | 20客户端并发同key | 一个bound资源，其余重放/处理中 |
| T03 | 同key不同参数 | 409，无第二执行 |
| T04 | 同key不同文件hash | 409，原输入绑定不变 |
| T05 | 同key不同owner | 隔离，不能返回他人资源 |
| T06 | 同key不同department | 不跨域重放旧记录 |
| T07 | 同key不同operation | 不串用创建/取消/发布记录 |
| T08 | registry新版本发布后旧key重放 | 返回原固定版本 |
| T09 | 描述数组/文件顺序有语义差别 | 指纹按schema区分，不盲目排序 |
| T10 | NaN/Infinity/损坏JSON | 拒绝，不能生成不稳定指纹 |
| T11 | 模型解析完成并保存后应答丢失 | 不重复解析已冻结输入 |
| T12 | 准备token过期，旧准备者晚落库 | 旧token不能绑定执行 |
| T13 | 创建run后插入step失败 | run/step/event/绑定全部回滚 |
| T14 | 初始event追加后注入异常 | 不发生隐式commit |
| T15 | DB提交成功但HTTP断开 | 重放查询到原资源 |
| T16 | 草稿并发消费 | 一个任务，草稿只绑定一次 |
| T17 | 同Native会话多条命令 | 均可保存，专用session关联正确 |
| T18 | 历史key歧义回填 | 标ambiguous，不删不乱选 |

## 9.3 授权、租约、重试测试

| ID | 场景 | 断言 |
| --- | --- | --- |
| T19 | 创建后撤销Skill权限 | 未启动任务拒绝执行 |
| T20 | 等待确认期间账号停用 | 不能确认/启动 |
| T21 | 管理员降为普通用户 | 刷新身份后按新权限处理 |
| T22 | 用户变更部门 | 不能把旧任务自动移到新部门执行 |
| T23 | 参数伪造owner/role | 服务端身份不变 |
| T24 | 撤权后停止自己Pi会话 | 允许合法停止，不允许新命令 |
| T25 | 其他用户取消/下载/猜ID | 按原scope政策拒绝 |
| T26 | 同worker_id不同attempt | 旧代次不能续租/发布 |
| T27 | heartbeat晚于租约过期 | 不复活过期资格 |
| T28 | 工作流旧heartbeat延迟到达 | 不续新代次租约 |
| T29 | 旧Worker执行完后新Worker已接管 | 旧结果登记失败，不改新状态 |
| T30 | DB暂断未超过租约 | 按政策恢复心跳，不假报成功 |
| T31 | DB断连超过租约 | 写入进入未知/人工恢复，不自动重跑 |
| T32 | waiting_user_action仍有进程 | 心跳、并发占槽、取消语义一致 |
| T33 | 风险字段缺失/损坏 | 不自动按只读重试 |
| T34 | read_only但声明修改上传文件 | 不自动重试 |
| T35 | RPA/Native/外部写入未知 | 禁止统一自动重试 |
| T36 | 确定只读、有效输入、未超次数 | 允许受控有限重试 |
| T37 | 取消与领取同时发生 | 最终只有合法执行/取消结果 |
| T38 | 子进程退出未确认 | 不释放危险副作用假设，不误报已取消 |

## 9.4 核销业务与恢复测试

| ID | 场景 | 断言 |
| --- | --- | --- |
| T39 | 两份同年度盈亏表 | 明确拒绝 |
| T40 | 缺流转表/多流转表 | 明确拒绝 |
| T41 | 跨年材料固定 | 年度映射不因当前日期变化 |
| T42 | 回放包跨用户/坏hash/缺文件 | 不可消费 |
| T43 | 只有预览、原包已清理 | 可看历史，不可当回放 |
| T44 | 回放模式尝试真实补取 | 拒绝，不调用业务系统 |
| T45 | 取数确认后补取版本变化 | 旧确认不自动覆盖新版本 |
| T46 | phase完成数组非合法前缀 | 拒绝推进 |
| T47 | Agent尝试跳过validate | 后端硬闸拒绝 |
| T48 | 证据只覆盖部分订单 | 不能标全量证据检查完成 |
| T49 | plan fingerprint改变 | 旧确认/写入请求失效 |
| T50 | stage失败 | 原材料/正式材料不变 |
| T51 | write_ledger成功、flow失败 | 不重跑已成功写入 |
| T52 | 写完后回读失败 | 仅恢复校验，保留写入证据 |
| T53 | 发布前父材料变化 | MATERIAL_VERSION_CONFLICT |
| T54 | 同父版本并发发布 | 仅合法后继成为current |
| T55 | 发布DB提交后应答丢失 | 回查原发布，不创建第二版本 |
| T56 | verified但正式台账登记未完成 | 恢复登记，不重写workbook |
| T57 | 多日第2日失败 | 第1日不重跑、第3日不提前启动 |
| T58 | 每日成功但范围报告失败 | 只恢复范围报告 |
| T59 | 恢复旧材料 | 创建新version，历史不覆盖 |
| T60 | 空业务日/延期/历史特殊分支 | 与原确定性基线一致 |
| T61 | stage/workspace文件被篡改 | hash/边界检查阻断 |
| T62 | 租约失效后仍返回成功脚本结果 | 拒绝发布 |

## 9.5 Pi、文件、发布与前端测试

| ID | 场景 | 断言 |
| --- | --- | --- |
| T63 | Pi submit/send重复投递 | 相同command只接受一次副作用 |
| T64 | UDS提交超时 | 回查同command，不换ID重发 |
| T65 | runtime重启 | 已登记job/receipt可恢复关联 |
| T66 | 重复/乱序事件 | 终态不被旧running覆盖 |
| T67 | 浏览器关闭/刷新 | 任务仍可查询，未重新创建 |
| T68 | 上传chunk重复/错误offset | 按协议拒绝或幂等，不损坏数据 |
| T69 | upload_commit重放 | 同版本不重复归档 |
| T70 | symlink/路径穿越/压缩包越界 | 拒绝，不读写scope之外 |
| T71 | 同hash不同owner | 不获得他人文件权限 |
| T72 | 正式成果登记失败 | 恢复归档，不重跑财务任务 |
| T73 | 删除时并发新增文件引用 | 不删除被引用文件 |
| T74 | 历史JSON引用未知 | 保守禁止删除 |
| T75 | task center混合来源 | 分页排序稳定、批次计数不重 |
| T76 | web/CLI并发发布 | 共用release事实与排他规则 |
| T77 | 发布中管理员更改暂停状态 | 旧操作不自动覆盖 |
| T78 | 目标Skill排空超时 | 恢复本次暂停，不取消任务 |
| T79 | 提醒Worker导入旧契约 | 拒绝不兼容热更新或完整发布 |
| T80 | 新镜像重启 | 版本与发布记录一致，无补丁丢失 |
| T81 | BFF自动重试不安全POST | 不重复执行；使用明确幂等策略 |
| T82 | 切换用户/部门 | 清理缓存，无跨用户残留 |
| T83 | SSE断线恢复 | 续读事件，不创建新任务 |
| T84 | 202/409/权限撤销/状态未知 | UI显示明确，不误报成功 |
| T85 | 核销业务页与通用组件共用 | 专有步骤/确认未丢 |
| T86 | 旧任务链接/下载入口 | 仍可解析或明确兼容重定向 |
| T87 | 干净环境完整build | 所有运行组件均可构建 |
| T88 | 无DDL权限API/Worker启动 | 兼容DB可ready，无隐式迁移 |
| T89 | 多迁移进程竞争/迁移失败 | 一次迁移，失败实例不ready |
| T90 | 数据与文件联合备份恢复 | 引用、材料、下载可用 |

## 9.6 Golden fixture 如何比较

Excel结果至少比较：工作表名/顺序、业务主键、单元格值、金额类型、币种、期间、公式文本、合并区域、必要数值格式、命名区域、隐藏行列和业务要求保留的样式。具体指标按原 Skill 的真实要求选择，不用“字节hash完全相同”作为唯一正确性标准。

生成时间、压缩包元数据、临时目录等非业务项可以按**明确白名单**归一化；不可忽略金额、公式、业务日期、材料版本或结果分类来让测试通过。

财务算法确定性测试不调用真实模型。模型工具选择测试使用固定响应 fixture；少量真实模型测试只有在授权和脱敏后执行，失败不能用来改变确定性基线。

## 9.7 并发测试要求

- 使用真实 PostgreSQL，独立连接/进程，不能用单个共享 Session 假装多客户端。
- 使用 barrier、latch、受控 fake clock、可注入故障点，不依赖随机 sleep 猜竞态窗口。
- 查询最终 DB记录与副作用计数，不能只断言 HTTP 200。
- 假脚本记录调用ID、phase、输入hash、写入计数；避免执行真实核销验证重试。
- heartbeat测试同时检查 affected rows 和最终代次，不能只看线程未报错。
- 每个 fault 测试明确“最后成功持久化点”和“预计允许恢复操作”。

<a id="chapter-10"></a>

# 10. 测试与工具命令

## 10.1 执行前提

先运行 PR-00实现的隔离验证。所有项目 import前已经配置专用测试数据库和数据目录，禁止自动加载生产 `.env`。原项目测试 fixture可能有自己的初始化方式，先读再执行；不能盲目运行完整 pytest 然后才检查它连了哪个库。

新安全包装器建议接口：

```text
python scripts/refactor/verify_isolation.py --profile isolated-tests
python scripts/refactor/check.py --suite backend-unit
python scripts/refactor/check.py --suite postgres-integration
python scripts/refactor/check.py --suite frontend
python scripts/refactor/check.py --suite contracts
python scripts/refactor/check.py --suite all
```

这些命令是**待新增的入口规范**，并非当前已有命令。包装器应：验证隔离、建立专用临时目录、设定环境、选择真实存在测试路径、传递退出码、写脱敏报告、拒绝生产目标。不要空实现后返回0。

## 10.2 已确认存在的前端脚本

在已经验证的本地/CI环境运行：[S25]

```bash
pnpm --dir web typecheck
pnpm --dir web lint
pnpm --dir web test:navigation
pnpm --dir web test:run-access
pnpm --dir web test:platform-data
pnpm --dir web test:agent-wire
pnpm --dir web test:hydration
pnpm --dir web build
```

依赖缺失时按已固定 packageManager/lock 安装；不要运行会隐式更新锁文件的大版本升级。lint既有失败写入基线；新改文件不增加失败。

## 10.3 合约生成与检查

先验证 isolated environment，且导入 app不会执行真实副作用后：[S30]

```bash
python scripts/export_openapi.py
pnpm --dir web contracts:generate
python scripts/export_openapi.py --check
pnpm --dir web contracts:check
```

第一、二条会写生成文件，属于开发更改；检查 git diff确认只有预期契约差异。不能为了让 `--check` 通过而删除生成字段或改成空 schema。

CI 应从源码再生成到临时目录或检查 tracked snapshot，不依赖开发者手动运行过一次。

## 10.4 后端命令参考

确认当前 Python解释器、依赖与隔离 fixture后，包装器可调用以下已有工具：[S29]

```text
python -m pytest -c backend/pyproject.toml backend/tests tests
python -m ruff check backend --config backend/pyproject.toml
```

测试目录以 PR-00确认存在且适用为准。按显式测试路径避免遗漏根 tests；若个别集成测试需要 Docker/UDS则标记并分套运行，不静默跳过。

`pytest` 的 basetemp会清理目标目录。包装器必须使用本轮独立临时路径，不能传入 `data/`、项目根、用户目录或共享临时目录。并行测试使用互不冲突的数据库和basetemp。

## 10.5 CI 最小工作流

```text
静态检查 ─┬→ Python单元/特征测试
          ├→ PostgreSQL并发与迁移测试
          ├→ 合约导出与TypeScript类型检查
          ├→ 前端测试与生产build
          └→ 正式镜像build/隔离smoke
                      ↓
              合并/发布门禁报告
```

第三方 GitHub Actions/容器镜像固定版本或digest并经审查；PR CI 不注入生产secret，不允许不可信分支直接操作自托管生产runner。测试artifact脱敏，不上传测试期间意外获取的真实数据。

<a id="chapter-11"></a>

# 11. 配置、环境和兼容开关

## 11.1 配置分类

| 类别 | 内容 | 管理要求 |
| --- | --- | --- |
| 业务参数 | 日期、材料、工具参数 | 每次任务固定，不能被全局开关改写 |
| 安全政策 | 授权、写入开关、网络出口、审批 | 服务端受控，默认保守 |
| 执行配置 | 池数量、租约、超时、runtime地址 | 配置校验与版本记录 |
| 发布配置 | revision、镜像digest、协议版本 | 来源明确、可回滚 |
| 凭据 | 数据库、模型、业务账号 | 密钥管理/受控文件，不进入任务上下文 |
| 兼容开关 | 新查询、新提交、旧入口退役 | 有负责人、默认值、适用范围、退役条件 |

## 11.2 必须保留并核对的已有配置

包括但不限于 `FINANCIAL_DATABASE_URL`、`FINANCIAL_DATA_DIR`、`FINANCIAL_AUTH_MODE`、`FINANCIAL_WORKER_COUNTS`、`FINANCIAL_PI_HARNESS_TOKEN`、`FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED`、`FINANCIAL_NETWORK_POLICY_MODE`、`AGENT_RUNTIME`、`AGENT_RUNTIME_FALLBACK` 以及 Pi manager 的 `PI_RUNTIME_ROOT/PI_MANAGER_SOCKET/PI_RUNTIME_IMAGE`。[S13][S22][S23]

名称出现在配置中不代表线上已启用。PR-00必须在不显示secret的前提下确认其支持范围和实际引用。

## 11.3 新开关只保留必要的短期兼容面

建议使用配置结构或命名一致的新设置表达：

| 建议能力开关 | 默认/用途 | 退出条件 |
| --- | --- | --- |
| submission_v2 | 隔离环境先开，正式环境经发布开 | 旧提交writer全部迁移后移除旧分支 |
| task_projection_v2 | 先只读影子比对，再切读 | 旧投影无调用且历史可读 |
| legacy_native_accept_new | 盘点前沿用当前行为；获证据后关闭 | 活跃旧命令归零且新功能覆盖 |
| runtime_protocol_v1 | manager与API兼容后启用 | 所有支持runtime升级 |
| enforce_schema_check | 正式启动必须开启 | 长期保留，不是可随意关闭的逃生阀 |

上述是**拟新增能力名**，实现时统一映射到实际 settings，不要原样新增多个含义重复的环境变量。

不要为租约、鉴权、哈希、写后校验添加普通管理员可关闭的开关。测试需要绕过外联时使用 fake connector，不能在生产代码埋全局 security_bypass。

## 11.4 兼容矩阵

每个 release 填写：API版本、Worker协议、AR契约版本、Pi manager协议、前端客户端合约、DB支持revision、Skill运行包版本、文件目录布局版本。

最重要的组合：

- 新API + 旧Worker：仅在执行契约和风险/租约语义兼容时允许。
- 旧API writer + 新幂等表：不能认为旧writer会自动遵守新幂等协议。启用强幂等前，相关旧writer必须排空并停止接收提交。
- 新API + 旧Pi manager：未支持命令去重时禁止自动重发副作用命令，必要功能标未就绪。
- 旧前端 + 新API：保持旧响应形状或提供适配，不能直接返回新receipt导致页面误判。
- 新DB + 旧应用：只在expand迁移兼容范围内允许；contract之后禁止未经验证回退旧代码。

## 11.5 业务时区与显示时区

核销业务日沿用现有业务时区规则；数据库时间戳统一带时区；前端可按既有显示规则展示。用户浏览器所在地或模型会话时区不能改变一个已经固定的核销日期。

相对日期在第一次创建时转换为明确业务日期并记录；幂等重放不重新解释“今天”。跨年材料映射不得根据容器UTC年临时变化。

<a id="chapter-12"></a>

# 12. 生产发布与回滚 Runbook

本章是供获授权的操作者执行的规范，不是本轮模型自动操作生产的授权。

## 12.1 发布之前

1. 确认所有P0门禁通过，未执行项有明确阻塞结论；核销金额差异未解释时禁止发布。
2. 固定候选源码SHA、镜像digest、依赖锁、DB目标revision、Skill包版本和manager协议。
3. 备份数据库、必要文件、发布记录与密钥恢复资料；验证备份可恢复，备份受控不打印内容。
4. 确认当前活动任务、等待确认任务、核销批次、Pi job、发布任务数量与协议版本。长任务是否可不中断共存必须先有测试证据。
5. 确认暂停范围是目标工具、目标入口或必要服务，不能默认停全站。
6. 检查旧API/Worker是否仍可能绕过新幂等/租约协议；没有兼容保证时对相关写入口排空切换，不进行随机流量混跑。
7. 保存当前配置指针、Skill状态generation、容器身份和镜像digest；之后回滚必须核对所有权，防覆盖后来的操作。
8. 单独执行迁移预检；大表索引、数据回填、scope修复不是普通“顺便发布”。

## 12.2 建议发布顺序

```text
部署可兼容的新Schema（expand）
    → 完成必要安全回填/预检
    → 限制受影响的新写入口
    → 排空不兼容旧Worker/API writer
    → 发布API与相应Worker/manager
    → 检查Schema、协议、网络、挂载、版本
    → 隔离/演示账号无副作用smoke
    → 恢复受影响入口
    → 观察错误、队列、租约、状态未知和材料冲突
    → 扩大允许使用范围
```

只读投影/UI可以影子比较；财务写入不做双执行影子。用于灰度的任务在创建时固定执行实现，新旧路由不得在任务中途切换。

“灰度”默认是明确工具/用户试点及固定版本，不是同一key重试随机落到新旧writer。流量分组不能来自可伪造客户端header。

## 12.3 上线后立即检查

- API/Worker/manager的源码和协议与release manifest一致。
- 无意外schema升级或SQLite导入。
- 普通任务仅领取一次，队列公平性与并发上限正常。
- 核销阶段/材料版本/批次串行未变化。
- Pi job状态与runtime一致，失联不是假失败，停止路径可用。
- 成果下载、历史文件、旧链接可访问。
- 没有新增越权、凭据暴露、错误重试、旧worker发布。
- 被暂停工具是否只由本次发布正确恢复，其他管理员状态未被改写。

不通过时停止扩大试点范围，按回滚/恢复矩阵处理。

## 12.4 必须触发停止扩大的条件

出现一例确认的跨用户数据访问、重复财务写入、旧代次成功发布、材料版本异常覆盖、快照版本漂移、自动重试未知写入，立即暂停相关新执行并调查。

普通前端样式缺陷或只读统计延迟可以局部回退，但不能为了尽快恢复界面关闭后端安全检查。

## 12.5 回滚分层

| 层次 | 可执行动作 | 不能误做 |
| --- | --- | --- |
| 前端 | 切回兼容镜像、保留新API适配 | 用旧客户端重新提交已执行命令 |
| API | 切回支持现有schema/receipt的兼容版本 | 绕过新幂等协议继续接写 |
| Worker | 停接单、等安全退出、切回兼容镜像 | kill全部进程后直接重排写任务 |
| Pi manager | 验证协议与活动环境后切换 | 清空owners目录或重建全部会话 |
| Skill包 | 核对release代次后恢复版本指针 | 修改在途任务snapshot |
| DB | 通常保留expand结构，后续forward-fix | 为回代码自动drop新表/数据 |
| 文件/材料 | 保留证据，按业务恢复新版本 | 用旧备份覆盖当前正式账簿 |
| 发布控制 | 仅恢复本次持有的pause/generation | finally无条件启用工具 |

## 12.6 断电/进程强杀后的恢复

先只读核验release receipt、实际镜像、包hash、DB当前材料、任务阶段、运行进程/容器身份。不要先重启全部服务再看结果，因为重启可能触发旧自动恢复或覆盖证据。

操作归属明确且未被后续管理员改变时，按对应操作记录恢复；状态不明确时保留暂停，报告 `recovery_required`。没有自动恢复把握时不能写“一键强制修复”。

## 12.7 幂等与数据库变更的发布特殊要求

幂等表上线前后存在旧writer窗口是高风险点。推荐顺序：先发布兼容schema与只读诊断，再暂停相关提交入口，完成旧writer排空，发布所有会创建任务的API/草稿/Agent入口新实现，验证后恢复写入口。

没有新增字段并不代表无兼容影响。重试政策、租约代次与状态变更也属于执行协议；新旧Worker混用须列入兼容测试。

<a id="chapter-13"></a>

# 13. 删除清单与证据要求

## 13.1 删除台账模板

| 字段 | 必填内容 |
| --- | --- |
| candidate_id | 稳定编号，例如 DEL-001 |
| path/symbol | 精确文件或函数，不能只写“旧代码” |
| category | 重复/生成/vendor/兼容/废弃功能/构建历史 |
| current_callers | 静态、动态、路由、部署、测试、外部客户端 |
| replacement | 替代位置/能力；无替代则说明获准取消 |
| runtime_evidence | 实际调用与活跃记录证据；缺失写unknown |
| historical_read_dependency | 历史任务/文件/协议是否依赖 |
| license_provenance | 需保留声明和来源 |
| tests | 对应成功执行的用例 |
| rollback | 恢复源码/配置/包的方法 |
| approval | 允许删除或blocked的具体依据 |
| result | 未改/仅隐藏/停新建/只读兼容/已删除 |

## 13.2 可优先清理的候选

| 候选 | 默认处理 | 删除条件 |
| --- | --- | --- |
| 互相矛盾的当前架构/Skill数量文案 | 更正、自动生成、历史归档 | 权威来源确定 |
| 重复业务无关UI组件 | 共用组件替代 | 动态引用、样式和E2E验证 |
| 日期补丁Dockerfile | 移出活动构建 | 完整构建和回滚替代已通过 |
| 试点启动脚本 | 统一入口后归档 | 所有支持环境仍可启动 |
| 旧Native同步命令writer | 停新建→只读→删除 | PR-18门禁 |
| legacy Agent回退 | 条件退役 | 不再承担唯一功能/回退职责 |
| 未用依赖 | 检查后移除 | build/runtime/dynamic/CSS均无引用 |
| 重复源码副本 | 固定唯一来源并生成 | 上游、patch、license和历史包可追溯 |

## 13.3 默认不删除

现有审计/审批/材料版本/引用保护、fencing与heartbeat、写后校验和恢复、原始取数与预览区别、关键合成fixture、数据库历史migration、仍需支持的协议解释器、真实文件和备份、Native包管理与Pi依赖、生产密钥、用户未提交改动。

禁用Skill不代表无历史依赖；低调用量不代表没价值；重复名称不代表重复实现；代码行数大不等于可以删算法。

## 13.4 删除后的验证

全仓精确引用检查、动态加载白名单、API contract、历史数据fixture、生产build、部署启动、许可证清单、任务恢复。未运行的验证不得勾选。

<a id="chapter-14"></a>

# 14. 最终验收与完成报告

## 14.1 必须全部满足的门禁

| 门禁 | 验收事实 |
| --- | --- |
| G01 | PR-00真实调用图、source-map、基线测试已建立 |
| G02 | 新提交具备数据库强幂等，历史Native会话无损迁移 |
| G03 | 任务/事件/步骤/初始引用提交原子，辅助事件无隐式穿透 |
| G04 | 权限撤销、停用、降权、部门变更测试通过 |
| G05 | 普通与Workflow旧代次不能续租/发布 |
| G06 | 自动/手动重试政策一致，不确定写入不会自动重排 |
| G07 | 队列公平性和维护份额验证，业务并发限制保持 |
| G08 | 核销新模块无反向依赖，原14阶段契约和财务结果保持 |
| G09 | 批次恢复不重跑成功日期，写后失败不重写已应用计划 |
| G10 | Pi命令/事件/后台任务可以重放去重和状态回查 |
| G11 | 正式文件与临时工作区区分，历史未知引用仍受保护 |
| G12 | 网页/CLI共享发布协议，完整源码可构建运行组件 |
| G13 | 前端合约生成、BFF、缓存隔离、旧深链测试通过 |
| G14 | API/Worker不执行隐式DDL，迁移/回填/恢复已演练 |
| G15 | 已删除内容逐项有证据，不存在未经证明的删除 |
| G16 | 无生产越权操作，生产是否上线有真实记录 |

有未满足门禁时，完成报告必须按 `passed/failed/not_run/blocked/not_applicable` 分类。`not_applicable` 必须说明理由，不能用来跳过难测项目。

## 14.2 最终报告模板

```markdown
# 架构改造最终报告
## 版本与范围
基线SHA、最终SHA、变更集、实际环境、生产是否操作。
## 已完成
按PR与门禁列事实，不只列目录。
## 修改映射
旧路径/符号→新位置→行为是否变化→测试。
## 数据变更
迁移revision、新增结构、回填统计、歧义记录、兼容范围。
## 测试
实际命令/退出码/结果，失败与未运行单列。
## 业务一致性
金额、材料版本、批次、写入、恢复的验证结果。
## 删除
已删/只读兼容/待证据对象。
## 部署与回滚
镜像digest、协议、发布记录、回滚演练。
## 剩余风险
必须有具体影响与下一安全动作。
```

## 14.3 定量目标如何使用

行数降低、模块数、删文件数量只能作为辅助指标，不能作为验收主要目标。推荐比较：循环依赖数量、新旧writer数量、未明确事务数、未覆盖高风险用例数、关键请求SQL次数、最老任务排队时间、成功恢复次数、未知文件引用数量。

目标由基线确定。不得虚构“减少40%代码”“性能提升3倍”等数字来填报告。

<a id="chapter-15"></a>

# 15. 交给编码大模型的启动与续接提示词

## 15.1 首次启动提示词

以下内容可以与本文件一起直接交给编码模型：

```text
你在维护 ErenYeager2002/financial_pj。请将随附的《financial_pj 完整架构改造执行手册》作为实施规范。
先完整阅读总指令、架构约束、不可破坏不变量、事务/数据协议和当前任务。
当前任务从 PR-00 开始，不一次性重写全仓。

先核对 git status、当前 SHA、AGENTS.md、项目实际目录与本文基线差异。
保留用户未提交改动；禁止生产写入、真实核销、发布、重启、删除数据、读取/输出secret；远程push/merge需要单独授权。
使用实际源码确认目标已经实现的部分，不重复造表、执行器和公共服务。

每个PR依次完成：调用与事务盘点、失败/特征测试、最小修改、专项及兼容测试、合约与文档、diff与敏感信息检查、真实执行报告。
使用 docs/refactor/progress.md 保存进度，使用 reports/PR-XX.md 保存修改与测试结果。
只在前置门禁通过后推进下一PR。缺少生产证据时保留旧路径并标记删除阻塞，不虚构零调用；可以继续不依赖该证据的开发。

现在直接开始 PR-00：生成执行路径、源码映射、事务边界、兼容与删除台账、合成回归基线及隔离测试入口。
先输出本PR拟处理文件与验证方式，再实施。不要只复述方案，不要将未运行测试写成通过。
```

## 15.2 单PR执行提示词

```text
继续 financial_pj 架构改造。先读手册与 docs/refactor/progress.md、最近报告、当前 git diff。
本次只执行 PR-XX：<从手册复制该PR标题>。
核对其所有前置PR和门禁，保留已有业务、安全、版本与历史兼容约束。
若已有等价实现，复用并补测试，不另造一套。

开始前列出：实际源文件/符号、调用者、读写表、文件或外部副作用、事务提交者、需新增的测试。
按手册实现，运行本PR专项测试及受影响兼容测试。
结束输出：真实修改文件、测试命令和结果、迁移/回填状态、未验证项、回滚方式、下一安全任务。
更新 progress.md 与本PR报告。没有运行能力的测试标 not_run，不以静态检查替代并发或沙箱验证。
```

## 15.3 会话耗尽后的交接提示词

```text
不要根据聊天记忆猜进度。读取完整手册、progress.md、最近两份PR报告和当前git状态。
先确认哪些变更已存在但未提交、哪些测试失败、哪个兼容开关已启用。
不得重跑真实任务、清空工作区或把已完成PR重新实现一遍。
从最近一个已通过门禁的恢复点继续下一个明确子任务。
如观察与文档不符，记录事实和修订计划后再改；不覆盖用户未提交修改。
```

## 15.4 独立代码审查提示词

```text
请审查本次PR，不继续开发无关功能。
重点检查：幂等唯一约束和并发、事务隐式commit、权限复核、scope、旧attempt写入、未知副作用自动重试、材料版本、批次已成功日重复写入、文件引用与删除竞态、运行时协议兼容、secret暴露。
逐条给出真实代码位置、触发条件、影响、测试缺口和最小修复建议。
不要仅按文件长度、命名或测试数量评分。不能证明的问题标为待验证，不能把测试未运行说成失败或通过。
```

## 15.5 删除审查提示词

```text
请只审查 deletion-ledger 中列出的对象。
对每个对象核对静态/动态/部署引用、运行证据、历史读取/恢复、替代能力、许可证与回滚。
任何一项缺证据，标记 blocked_for_removal；不要把“没搜到”当“无人使用”。
不得删除真实数据、快照、材料、migration、密钥、历史协议或仍被新Pi使用的Native包。
通过后输出具体可删路径和对应测试；未获授权不执行生产删除。
```

<a id="chapter-16"></a>

# 16. 逐PR给模型的最小输入与输出

| PR | 每次额外提供的输入 | 必须输出的核心证据 |
| --- | --- | --- |
| 00 | 仓库本地访问、现有AGENTS/文档 | 调用图、测试环境、现有失败 |
| 01 | database/env/所有init_db调用 | 迁移单入口、无DDL启动测试 |
| 02 | commit调用表、Run创建调用链 | 回滚注入测试、commit归属 |
| 03 | key语义、Native旧数据fixture | 并发20请求与回填结果 |
| 04 | 权限/角色/部门政策fixture | 各边界撤权/降权测试 |
| 05 | lease与风险manifest样本 | 旧attempt拒绝、未知写入不重试 |
| 06 | 队列/池/并发作用域 | 饱和队列公平性和维护份额 |
| 07 | 现有API/OpenAPI/BFF映射 | 路由diff与兼容结果 |
| 08 | AR私有依赖/脚本副作用清单 | 单向依赖测试与port注入 |
| 09 | 固定材料/取数包/回放fixture | 取数预览与scope一致 |
| 10 | 原phase/计划/证据golden | 14阶段顺序和计划对比 |
| 11 | 写入阶段故障点 | 原材料不变、写入证据与恢复 |
| 12 | 批次/发布/报告失败fixture | 成功日期不重写、发布唯一 |
| 13 | manager/jobs实际协议 | command去重与超时回查 |
| 14 | 文件引用/历史JSON/Pi产物 | 归档与删除竞态、统计去重 |
| 15 | 两种发布入口/包来源 | release同源、并发与回滚测试 |
| 16 | 现有页面/组件/查询key | BFF/缓存/幂等/旧链接测试 |
| 17 | 所有构建与systemd入口 | 干净构建、协议与挂载验证 |
| 18 | 新旧调用证据、覆盖矩阵 | 退役证明或保留阻塞结论 |
| 19 | 基线资源和故障环境 | 脱敏观测、性能与故障报告 |
| 20 | 全部清理候选与替代 | 删除台账、license、build |
| 21 | 全部PR报告与门禁 | 最终验收/部署/回滚包 |

<a id="chapter-17"></a>

# 17. 常见实现陷阱检查表

- [ ] 是否把会话 ID 当作幂等键，导致同一会话无法执行第二条命令？
- [ ] 是否在查询旧 key之前读取最新版Skill，破坏跨版本重放？
- [ ] 是否将数据库唯一约束异常捕获后继续使用已失败事务？
- [ ] 是否以为 savepoint 的提交等于整个事务提交？
- [ ] 是否在外层原子事务里调用默认commit的event/storage/权限函数？
- [ ] 是否用 `with_for_update` 锁查询却在发布前换了Session失去锁与fence？
- [ ] 是否在一个路径先锁全局再锁task，另一路反过来，造成死锁？
- [ ] 是否认为租约到期意味着旧子进程已经退出？
- [ ] 是否让旧heartbeat重新激活过期租约？
- [ ] 是否将输出副本生成与写原始账簿都标为相同read_only？
- [ ] 是否把按钮禁用当作防重复提交的唯一措施？
- [ ] 是否因用户撤权而禁止其合法停止正在消耗资源的会话？
- [ ] 是否把文件存在和同hash当作授权依据？
- [ ] 是否以“引用表为空”证明历史JSON记录没有引用？
- [ ] 是否在清理前只查一次引用而未处理并发新增引用？
- [ ] 是否将原始包清理后剩下的预览当作可回放数据？
- [ ] 是否将核销报告失败映射成全批次需要从头重跑？
- [ ] 是否为了拆分代码改变phase名称、默认年份、Decimal/舍入或顺序？
- [ ] 是否为旧Native另造队列，而新Pi已经有jobs？
- [ ] 是否删除native包目录，导致新Pi无法挂载已安装Skill？
- [ ] 是否把runtime失联显示成确定失败并自动重发命令？
- [ ] 是否把跨来源第一页拼接当作正确全局分页？
- [ ] 是否手工修改generated.ts而没有更新OpenAPI？
- [ ] 是否把当前用户数据缓存到不含scope的Query key/server cache？
- [ ] 是否在发布finally里无条件恢复工具，覆盖管理员暂停？
- [ ] 是否只改运行容器文件，没有更新重启后使用的镜像或包指针？
- [ ] 是否把schema升级和历史SQLite数据导入放在每次启动一起执行？
- [ ] 是否声称SQLite通过就证明PG行锁/并发正确？
- [ ] 是否把`data/`传给pytest basetemp导致清理真实文件？
- [ ] 是否只留下目录、接口空壳、TODO和测试mock，却报告已重构完成？

<a id="chapter-18"></a>

# 18. 来源、证据与版本说明

## 18.1 仓库来源

本仓库来源链接均固定到基线提交。实施时从真实工作副本按符号定位，不按本手册的历史行号批量修改。某个文件被列为修改对象但未在本次全文阅读的，已经要求执行模型先完整阅读；列出路径不等于宣称已审计其全部内容。

| 标记 | 基线源码 | 核查内容 |
| --- | --- | --- |
| [S01] | `README.md` | 项目用途、运行入口、源码同步与快照说明 |
| [S02] | `CONTEXT.md` | 平台术语、任务/材料/提醒/审批/发布区别 |
| [S03] | `backend/app/main.py` | API入口、生命周期与路由组装 |
| [S04] | `backend/app/run_service.py` | 普通任务创建、幂等、文件校验、确认与重试 |
| [S05] | `backend/app/run_fencing.py` | 普通任务租约与代次校验、before_flush保护 |
| [S06] | `backend/app/worker.py` | 任务领取、执行、attempt目录与维护调度 |
| [S07] | `backend/app/models.py` | Run、材料版本、Artifact/Approval绑定与约束 |
| [S08] | `backend/app/native_skill_service.py` | Native安装、固定包、会话哈希、同步命令与Run登记 |
| [S09] | `backend/app/routers/pi_runtime.py` | Pi会话、operate、jobs、文件上传与下载接口 |
| [S10] | `backend/app/pi_runtime_service.py` | Pi会话目录、权限复核、文件锁与UDS调用 |
| [S11] | `backend/app/workflow_service.py` | 核销、批次、写入、异常与恢复的现有集中实现 |
| [S12] | `backend/app/ar_execution_runner.py` | AR阶段执行、执行资格与反向service依赖 |
| [S13] | `deploy/production/compose.yaml` | 基础生产PostgreSQL、session、Worker与Agent配置 |
| [S14] | `backend/app/events.py` | emit_event默认commit行为和失败审计 |
| [S15] | `backend/app/scheduler.py` | 调度锁、自动重试政策、过期恢复、并发计数 |
| [S16] | `backend/app/leases.py` | 普通与workflow心跳条件的当前差异 |
| [S17] | `backend/app/database.py` | init_db迁移、SQLite兼容、engine/session |
| [S18] | `backend/alembic/env.py` | online/offline迁移和连接创建 |
| [S19] | `backend/app/ar_execution_contract.py` | ar-execution-v2、14个阶段、连续前缀与发布待完成 |
| [S20] | `backend/app/workflow_material_service.py` | 固定材料、年度检查、历史lineage与发布相关能力 |
| [S21] | `deployment/README.md` | 单工具宿主机发布、排空、状态归属、失败回滚 |
| [S22] | `deployment/compose.pi-runtime.yaml` | Pi模型代理、出口、Native包挂载与资源限制 |
| [S23] | `deployment/financial-pi-runtime.service` | 宿主机manager的路径、镜像与systemd限制 |
| [S24] | `deployment/Dockerfile.pi-context-api` | 基于日期基础镜像覆盖少量源码的例子 |
| [S25] | `web/package.json` | 技术栈、测试脚本、OpenAPI生成与包管理版本 |
| [S26] | `web/src/config/platform-navigation.ts` | 员工与管理导航及现有入口 |
| [S27] | `web/src/features/agent-runtime/agent-wire.ts` | 同名feature目录中的共享协议文件；不应按名称认定重复引擎 |
| [S28] | `backend/app/authorization.py` | 当前用户刷新、Skill权限与管理权限更新事务 |
| [S29] | `backend/pyproject.toml` | Python依赖、pytest与ruff配置 |
| [S30] | `scripts/export_openapi.py` | 稳定OpenAPI导出、--output和--check |

[S01]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/README.md
[S02]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/CONTEXT.md
[S03]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/main.py
[S04]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/run_service.py
[S05]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/run_fencing.py
[S06]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/worker.py
[S07]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/models.py
[S08]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/native_skill_service.py
[S09]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/routers/pi_runtime.py
[S10]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/pi_runtime_service.py
[S11]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/workflow_service.py
[S12]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/ar_execution_runner.py
[S13]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/deploy/production/compose.yaml
[S14]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/events.py
[S15]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/scheduler.py
[S16]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/leases.py
[S17]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/database.py
[S18]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/alembic/env.py
[S19]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/ar_execution_contract.py
[S20]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/workflow_material_service.py
[S21]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/deployment/README.md
[S22]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/deployment/compose.pi-runtime.yaml
[S23]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/deployment/financial-pi-runtime.service
[S24]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/deployment/Dockerfile.pi-context-api
[S25]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/web/package.json
[S26]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/web/src/config/platform-navigation.ts
[S27]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/web/src/features/agent-runtime/agent-wire.ts
[S28]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/app/authorization.py
[S29]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/backend/pyproject.toml
[S30]: https://github.com/ErenYeager2002/financial_pj/blob/2cd58e91348ff566250f03b882f22c46425bbe1f/scripts/export_openapi.py

分支复核来源：`https://api.github.com/repos/ErenYeager2002/financial_pj/branches/main`；最终实施应再次记录当时HEAD。


## 18.2 外部技术资料

以下资料用于支撑少量框架/数据库机制与架构参考，本文具体任务、字段、状态和迁移顺序是针对本项目提出的设计方案，并非第三方项目的现成实现。

[E01]: https://www.windmill.dev/docs/advanced/self_host
[E02]: https://www.activepieces.com/docs/install/architecture/piece-syncing
[E03]: https://github.com/langgenius/dify
[E04]: https://github.com/midday-ai/midday
[E05]: https://docs.sqlalchemy.org/en/20/orm/session_transaction.html
[E06]: https://alembic.sqlalchemy.org/en/latest/cookbook.html
[E07]: https://www.postgresql.org/docs/16/sql-select.html

- [E01] Windmill 自托管架构：PostgreSQL、服务端与Worker职责。
- [E02] Activepieces 组件同步与版本固定。
- [E03] Dify 官方仓库：模型、工具与AI工作流能力范围。
- [E04] Midday 官方仓库：财务文件、任务与助手的产品组织。
- [E05] SQLAlchemy 2.0事务、savepoint与Session管理。
- [E06] Alembic Cookbook：程序化迁移与共享连接等模式。
- [E07] PostgreSQL 16 SELECT与锁定子句，含SKIP LOCKED。

外部文档可能更新。实际实施应以项目已锁定依赖版本支持的API为准，不因为文档出现更高版本就顺带升级全项目。

## 18.3 本文交付状态

**已完成的是本实施文档的编写与结构检查。未完成、也未声称完成的是仓库代码改造、数据库迁移、全仓测试和生产上线。**

将此文交给编码模型后，真实完成情况只能由逐PR代码diff、测试执行记录、迁移报告和发布证据证明。

<a id="appendix-a"></a>

# 附录 A：文件级修改索引

本索引用于编码模型定位；`保留/委托/拆分/新增`是预期动作，不是已执行事实。标为“调用盘点后”的对象必须先读实现和引用。新增目录可以按既有规范调整，但职责和单向依赖不得改变。

| 当前文件/目录 | 动作 | 具体改动 | PR |
| --- | --- | --- | --- |
| `backend/app/database.py` | 拆分 | DDL迁出；运行期schema检查；legacy基线导入独立；保持engine/session兼容 | 01 |
| `backend/alembic/env.py` | 修改 | 支持受控共享connection；保持offline；全模型元数据注册 | 01 |
| `backend/alembic/versions/` | 新增revision | 增量幂等/关联/必要索引；不改已执行历史迁移 | 01、03、14、15 |
| `backend/app/main.py` | 瘦身 | lifespan去隐式迁移；路由迁出；旧Nativereaper按退役条件去除 | 01、07、18 |
| `backend/app/events.py` | 接口分层 | 新append无commit；旧emit作过渡wrapper；保持fencing和脱敏审计 | 02 |
| `backend/app/audit_service.py` | 审查/修改 | 明确无隐式提交的事件追加入口；保留审计字段与权限 | 02、19 |
| `backend/app/run_service.py` | 拆用例 | 准备/持久化分离；幂等回执；确认授权；统一重试政策 | 02～05 |
| `backend/app/draft_service.py` | 修改 | 草稿消费与run绑定原子；重复确认不双建 | 02、03 |
| `backend/app/step_runtime_service.py` | 修改 | 使用调用方事务；保持步骤状态与绑定；重试按明确风险 | 02、05 |
| `backend/app/models.py` | 保留入口/增量 | 导入新增模型；保留原表/约束；只增必要字段，避免ORM类重复 | 03、14、15 |
| `backend/app/authorization.py` | 复用 | 当前身份刷新、Skill权限作为底层；管理事务单独审查 | 04 |
| `backend/app/auth.py` | 边界核查 | 保留会话核验，不信任客户端scope；Worker使用真实当前用户 | 04 |
| `backend/app/resource_policy.py` | 收敛 | 文件/任务scope共用策略；旧历史规则明确 | 04、14 |
| `backend/app/worker.py` | 修改 | 无隐式迁移；启动授权；领取公平性；明确租约/维护份额 | 01、04～06 |
| `backend/app/scheduler.py` | 修改 | fail-closed重试；代次恢复；公平性；锁顺序统一 | 05、06 |
| `backend/app/leases.py` | 修改 | workflow绑定attempt与未过期条件；rowcount/失效观测 | 05 |
| `backend/app/run_fencing.py` | 保留/补测 | 保留before_flush；确保新事务Session继承正确fence | 02、05 |
| `backend/app/adapters.py` | 逐步抽特例 | 普通执行保留；业务skill特例经回归后放业务扩展钩子 | 05、08、后续小步 |
| `backend/app/workflow_service.py` | 渐进拆分 | 取数/材料/阶段/写入/发布/批次迁出；剩单向兼容facade | 08～12 |
| `backend/app/ar_execution_runner.py` | 改依赖 | 不反向import旧service；公开端口；phase与lease边界保持 | 05、08～12 |
| `backend/app/ar_execution_contract.py` | 纯领域迁移 | 14phase/前缀/guard固定；旧导入显式re-export | 08、10 |
| `backend/app/ar_snapshot_contract.py` | 保留/适配 | 固定契约/包hash校验；批次首日与后续一致 | 08、15 |
| `backend/app/ar_annual_materials.py` | 保留/归位 | 年度映射来自固定材料；不随当前年份重猜 | 08、09 |
| `backend/app/ar_process_evidence.py` | 保留/端口包装 | 子进程身份、退出证据、timeout、调用关联 | 08、11 |
| `backend/app/workflow_material_service.py` | 应用/仓储拆分 | 固定材料查询、lineage、发布CAS、历史恢复不覆盖 | 09、12 |
| `backend/app/fetched_bundle_service.py` | 复用/归位 | 原始取数包、回放、保留与权限保持 | 09 |
| `backend/app/fetched_data_preview.py` | 修改边界 | 派生分页预览，不回退原文；与原bundle状态区分 | 09 |
| `backend/app/workflow_execution_policy.py` | 复用 | 业务执行开关、身份、回放等与公共授权协同 | 04、09 |
| `backend/app/workflow_orchestrator.py` | 边界收敛 | 模型决策仅请求允许动作；阶段硬闸共用 | 10 |
| `backend/app/ar_publication.py` | 调用盘点后归位 | 材料发布结果、回执与恢复边界，不另造版本表 | 12 |
| `backend/app/ar_execution_recovery.py` | 调用盘点后归位 | 明确阶段恢复/不确定写入；禁止从头重跑 | 12 |
| `backend/app/ar_report_recovery.py` | 调用盘点后归位 | 范围报告失败不推翻已成功日期 | 12 |
| `backend/app/ar_formal_ledger_service.py` | 调用盘点后归位 | 已发布后的正式台账登记恢复 | 12 |
| `backend/app/ar_staging_retention.py` | 修改调用边界 | 无活跃/恢复引用才清理；维护任务份额 | 06、11、19 |
| `backend/app/task_reminder_workflow_service.py` | 复用 | 提醒只预填，成功/失败关联保持 | 09、12 |
| `backend/app/native_skill_service.py` | 分职责 | 安装/包/历史保留；同步执行按证据退役；迁会话key | 03、13、15、18 |
| `backend/app/native_skill_policy.py` | 复用 | native权限与固定工具权限不混淆 | 04、13 |
| `backend/app/routers/assistant.py` | 调用盘点后修改 | 草稿/Native旧writer适配；保留历史查询 | 03、18 |
| `backend/app/routers/pi_runtime.py` | 修改 | 强类型操作、稳定命令回执、当前scope、合法cancel | 13、14 |
| `backend/app/pi_runtime_service.py` | 修改 | UDS协议、会话锁、重放/查询关联；第一轮保留单机索引 | 13 |
| `backend/app/pi_skill_bindings.py` | 复用/修改 | 固定包revision、挂载授权、撤权停止策略 | 04、13、15 |
| `backend/app/pi_business_access.py` | 调用盘点后修改 | 窄业务能力、短期关联、不能扩大正式写权限 | 04、13 |
| `backend/app/pi_model_access.py` | 调用盘点后修改 | 保持Key不进模型环境；关联scope与调用trace | 13、19 |
| `backend/app/pi_model_broker.py` | 调用盘点后修改 | 模型受控出口/数据读取边界；不直接新建任务引擎 | 13、17、19 |
| `backend/app/storage.py` | 拆端口/复用 | 正式成果登记、流式复制、hash、引用与事务边界 | 02、14 |
| `backend/app/file_service.py` | 修改 | 详情/删除共用引用判断；历史保护与分页 | 14 |
| `backend/app/task_center_service.py` | 修改 | 新Pi投影、稳定全局分页、batch计数保持 | 14 |
| `backend/app/workbench_service.py` | 修改 | 共用任务查询口径，明确统计scope与时间窗 | 14 |
| `backend/app/registry.py` | 增量扩展 | 固定version/hash/契约；不执行remote main | 15 |
| `backend/app/skill_source_service.py` | 调用盘点后收敛 | 来源发现/固定revision，不与发布抢写 | 15 |
| `backend/app/skill_install_service.py` | 调用盘点后收敛 | 包完整性、安全校验、来源与license | 15 |
| `backend/app/skill_rollout_service.py` | 调用盘点后收敛 | release状态、目标排空、操作代次和恢复 | 15 |
| `backend/app/skill_availability_service.py` | 修改协作 | 暂停归属/generation；恢复不覆盖他人操作 | 15 |
| `backend/app/runtime_health_service.py` | 修改 | 区分liveness/readiness/管理员观测，统计真实状态 | 19 |
| `backend/app/task_errors.py` | 扩展 | 结构化错误与恢复政策，不掩盖未知副作用 | 05、19 |
| `web/src/config/platform-navigation.ts` | 保留/优化 | 保留七入口职责，管理导航与权限分开 | 16 |
| `web/src/features/platform-api/` | 复用/更新 | OpenAPI生成、稳定类型别名、作用域/错误适配 | 07、16 |
| `web/src/features/pi-runtime/` | 提取共用/适配 | 命令ID、jobs状态、成果、断线恢复；不重造runtime | 13、16 |
| `web/src/features/workflows/` | 保留专用体验 | 材料/日期/取数/证据/批次恢复保留 | 16 |
| `web/src/features/ai-chat/` | 调用盘点后适配 | 真实任务卡、草稿区别、消息与状态分离 | 16 |
| `web/src/features/task-center/` | 共用查询 | 去重统计、稳定分页、状态未知 | 14、16 |
| `web/src/features/files/` | 共用组件 | 正式文件、临时文件、引用保护、授权下载 | 14、16 |
| `web/src/app/api/platform/` | 修改BFF | 透传request/key、状态码、流；防跨用户cache | 16 |
| `web/package.json` / lock | 最后清理 | 保留有效测试/生成脚本；无依赖证据才删 | 17、20 |
| `scripts/export_openapi.py` | 验证/小改 | 无生产副作用导出，保持--check | 07、16 |
| `deploy/production/compose.yaml` | 修改 | 迁移一次、服务协议/镜像、资源/网络/健康 | 01、17 |
| `deployment/compose.pi-runtime.yaml` | 归一配置 | 保持broker/egress隔离与Native包挂载 | 17 |
| `deployment/pi_runtime_manager.py` | 阅读后迁源码 | 搬到runtime-manager并保留旧启动wrapper | 13、17 |
| `deployment/native_agent_jobs.py` | 阅读后适配 | 共用command receipt，不建立第三套jobs | 13、17 |
| `deployment/deploy_tool.py` | 阅读后适配 | 共用release事实，保留排空与回滚保护 | 15 |
| `deployment/financial-pi-runtime.service` | 参数化安装 | 移除个人release硬路径，保留安全限制 | 17 |
| `deployment/Dockerfile.*` | 替代后归档 | 不再是干净构建必需补丁链 | 17、20 |
| `sources/`、`skills/`、`standalone-skills/`、`native-skill-overrides/` | 仅盘点后清理 | 唯一维护源、构建产物、license、历史快照分开 | 00、20 |
| `docs/refactor/` | 新增 | 真实进度、报告、迁移、删除与回滚依据 | 全程 |
| `scripts/refactor/` | 新增 | 只读盘点、安全测试包装、dry-run回填与校验 | 00、03、14、21 |

以上为定位索引，以 `git ls-files` 和实际源码为准；不因为目标目录名称相似而新建另一份同义实现。

<a id="appendix-b"></a>

# 附录 B：任务调度清单格式

编码模型可以在PR-00把下列结构实现为 `docs/refactor/tasks.yaml`。这是规划清单，不是自动执行全部生产操作的脚本。

```yaml
schema_version: refactor-plan-v1
repository: ErenYeager2002/financial_pj
baseline_commit: 2cd58e91348ff566250f03b882f22c46425bbe1f
execution_policy:
  one_change_set_at_a_time: true
  preserve_uncommitted_changes: true
  production_mutations_authorized: false
  remote_push_merge_authorized: false
  use_synthetic_data: true
  unknown_write_auto_retry: false
  tests_not_run_must_be_reported: true
states:
  - pending
  - in_progress
  - passed
  - blocked
  - failed
  - already_satisfied
record_fields:
  - task_id
  - depends_on
  - source_files
  - added_files
  - invariants
  - migrations
  - test_ids
  - actual_commands
  - actual_exit_codes
  - rollback
  - blockers
  - report_path
```

不得把YAML里的任务状态默认初始化为passed。每个PR通过需要真实报告；缺少生产证据的退役任务可以blocked，但其保留兼容实现的开发子项可以单独通过，不混淆两者。
