# CW06 / F4.E1 — 首次日清原进程观察锚点

Status: design-review pending; formal specification only. 本节点未授权产品或测试修改，须 root 设计审查后另行授权首个真实 red。

## Problem Statement

现有 CW06 / F4.B–D 在 effect 原 attempt 中保留 prepared / terminal refs，F4.C 默认关闭的只读详情不制造缺失原 SHA。`build_initial_report` 已有计划与真实子进程入口，却不在 effect 登记路径内；旧 result / failure payload 会随动作后续 attempt 改变，不能作为这一原进程的不可变归属来源。缺失观察不证明没有启动、没有输出或没有金融影响。

F4.D 已完成源码、针对性测试、独立两轴审查、后端发布、runtime 和实际官方浏览器验收；正式节点 SHA256 为 `9958648042f526efaaa7a9b63ddd9d1aeeb9a09e5ac158ed8b235ba43fe6da2a`。E1 只补这一阶段的原进程观察，不把 F4 或完整 attempt 宣告完成。

## Solution

在现有 `execution_safety_v1` 中增加独立 `process_observations` 引用分区。只为已有计划的 `ar_build_initial_report` 登记原 binding、提交确认过的 prepared ref，以及原 producer finally 捕获的 immutable terminal ref。复用现有 frozen anchor / observation、原生 Linux supervisor、fresh claim / permission / material fences、独立 prepared / terminal 事务和 system Audit；以服务端固定的分区选择接线，不另建任务库、表、锁服务或第二套权限体系。

保留现有阶段调度、生命周期、材料占用、输出和结果 transition。观察完整与否均不授权重试、解除占用、恢复或管理员财务写。该阶段只有一个脚本入口；不泛化其它 non-effect 或 investigation 路径。

## User Stories

1. 作为任务所有者，我希望原首次日清子进程的观察可归属原 attempt，避免后续动作结果覆盖其出处。
2. 作为运行维护者，我希望 prepared commit 成功回执之前不能 spawn，保持真实取消、lease、权限与输入绑定 fences。
3. 作为审查者，我希望晚到 producer 只能保留原观察，不改新 attempt、业务状态、材料或新计划。
4. 作为审查者，我希望部分原 SHA、登记失败和历史缺失保持未知，不从文件补造原指纹。
5. 作为平台使用者，我希望默认关闭的 effect 详情、历史统计和公开 DTO 保持原含义，不把观察误认为完成或恢复许可。
6. 作为维护者，我希望实际 PG / benign no-op 测试与运行验收分别留证，失败及未覆盖边界显性保留。

## Implementation Decisions

### 1. 真实入口与依赖

阶段契约要求已有 completed prefix：`inspect_materials → classify_receipts → review_order_evidence → validate_reconciliation`，当前请求为 `ar_build_initial_report`。校验阶段产生 `checked_plan`、`plan_fingerprint` 及原 material binding；真实 handler 仅调用一次 `self.script("build_worklist.py", ...)`，参数包含 workspace、核销日期、原 checked_plan 和 out。

脚本不在 cached-command 白名单内，classic / lab 均保持该原 basename；它不触发只适用于其它原脚本名称的后续 history guard。E1 必须在服务端同时限制 phase 与 original / actual script 为上述组合；任何后续缓存替换或第二子进程不能自动纳入。本阶段不得修改 cache / historyguard 接线。

真实脚本仍可能在同进程生成 flow plan JSON、batch ledger、日清文件，并对报告 ZIP 作静态整理。这些输出沿用现有路径及行为，不称为完全文件只读、`no_effect_verified` 或可安全自动重试；E1 不为这些 in-process 写入建立金融事实或输出证明。观察产生只表示 producer 实际观察。

### 2. 精确存储与版本

唯一新增存储为 `context.execution_safety_v1.process_observations`，严格对象字段为 `schema_version`、`revision`、`attempts`；schema 为 `ar-process-observations-v1`，revision 为非负真 int，attempts 上限 128。不存在该分区表示 legacy 未登记，不触发补录。遇无 outer v1 索引时，仅建立既有合法 skeleton（`ar-execution-safety-v1`、effect revision 0、effect attempts []）容纳观察分区，不新造 effect entry。

每条 observation attempt 严格包含以下 18 个字段：原有 14 个 `BINDING_FIELDS`：`workflow_id, action_id, attempt, phase, worker_id, owner_id, department_id, skill_id, skill_hash, material_set_id, material_version, reconciliation_date, plan_fingerprint, workspace_sha256`；另有 `binding_sha256, intent_at, prepared_process_refs, terminal_process_refs`。phase 只能是 `build_initial_report`。不含 business status、completion/result digest 或 effect disposition；refs 的两个数组对新 entry 显式存在，可为空。相同 action / attempt 只能有一条 observation entry，不能通过换 phase 覆盖。

binding digest 继续采用既有 14 字段 canonical JSON / SHA256 规则，摘要是完整性桥接而非授权 token。attempt / material_version 均为正真 int，字符串身份字段非空且上限 255 字符；日期采用当前原值，phase 固定；skill_hash / plan_fingerprint / workspace_sha256 / binding_sha256 均为 64 位小写 hex；时间为有 UTC offset 的 ISO 字符串且上限 64。工作目录只保存 UTF-8 字符串 SHA，不把绝对路径或 raw plan 加入引用。

prepared ref 复用现有 exact 8 字段及 `ar-process-evidence-v1` 校验：`schema_version, record_id, prepared_sha256, script, script_sha256, arguments_sha256, binding_sha256, registered_at`。terminal ref 复用 exact 10 字段：`schema_version, record_id, prepared_sha256, script, started_sha256, exit_sha256, domain_exit_sha256, terminal_state, binding_sha256, registered_at`。script 只允许 `build_worklist.py`；record_id 为 32 位小写 hex。每条 E1 attempt 最多一个 prepared 及其最多一个 terminal，单 action 所有 observation attempts 的 prepared 总数不超过现有 MAX_RECORDS=128；record ID 不得与同 workflow effect prepared refs 或其它 observation refs 重复。缺失与 null 不混为一谈；terminal 的三个 nullable SHA 保留既有验证，状态只取 `exited / exit_unconfirmed / launch_unconfirmed`。

observation revision 在 intent、prepared、首次 terminal 登记时各增一次；精确重复 terminal 不增。outer effect revision / attempts、既有 effect refs 均不因 observation 登记改写。新分区坏类型、超限、坏 digest 或 bridge 仅阻断 E1 的追加；effect reader / admission 不读取它，也不因该分区产生完成或解除占用。outer 已有 effect v1 本身坏类型时仍按现有规则拒绝，不旁路。

### 3. 原 binding、意图与启动接线

在实际 `execute_phase` 中，当前阶段 / completed-prefix / 原 claim / owner / material 校验成立后，将 observation intent 加入 fresh workflow context；使用既有阶段调用方拥有的 commit 边界提交。纯 context registrar 不 commit / rollback 调用方，不增加隐式调用方 flush。binding 取已核实的原 workflow、action 原 attempt / worker、ar_execution material、workspace 和原计划；checked_plan 必须存在于原 workspace，当前 bytes SHA 与原 plan_fingerprint 相符。缺 checked plan 或原 digest 无效即拒绝，不能猜最新 plan、换 basename、从最新 attempt 补身份或为 legacy 补 SHA。

构造器原有 self.context 是 intent 之前的快照，不得用其缺分区误判；script / gate 选择只从 fresh workflow context 中取得当前唯一原 observation entry，并冻结绑定摘要传给原 producer。producer 的 `PreparedProcessAnchor` 既有 optional binding_sha256 和 ten-field prepared identity 已足够，不新增另一 frozen authority wrapper；分区选择是本次调用内部固定值，不能由请求参数指定，不能依据晚到时当前 action 名称选择。

复用同一 launch gate / terminal registrar 事务体，以小接口选择 effect 或唯一 E1 observation 分区。effect 默认分支与原签名兼容；其它 non-effect 调用仍走原路径。保留全局 claim 锁 → action row → workflow row 顺序，独立 Session / engine，原 owner permission、原材料、abandon、cancel、stop、lease、attempt、worker fences 不减少。两次 fresh gate 均核对当前 checked_plan 在原 workspace 且其 bytes SHA 等于冻结原 plan_fingerprint；只能核对输入完整性，不能分析金融结果。prepared ref + 原 prepared Audit 在第一独立事务原子提交，成功回执后才进入 invocation-local bounded confirmed record 集。第二 fresh gate 校验完整原 bridge 与原登记，真实 Popen 和 started fact 位于现有 gate 窗口；退出 gate 的 rollback / 释放锁发生在 communicate / timeout / cleanup 等等待之前。

prepared duplicate 拒绝再次 spawn；prepared Audit SQL / fsync / gate 错误保留原异常及 cause。prepared commit 前失败或 commit 回执丢失不把该 record 加入 confirmed 集，terminal callback 不执行 SQL、不覆盖原 error；即使数据库可能已有 prepared，ack-lost 情形仍是 terminal 缺失 / unknown，不反推没有启动。

### 4. terminal capture、原桥接与晚到

沿用 producer outer finally：真实 communicate、supervisor receipt 验证、cleanup、termination callback 移除后，用 producer 已赋值且 fsync 返回后的原 SHA 冻结 observation。started / exit / domain facts 任一未获得原 SHA 就为 null；不读取残存或被损坏文件重算，终态不升级为业务完成。cleanup / fsync / receipt validation 的原原因链必须保留；不存在 confirmed prepared 时保留 gate / producer 原 error。

terminal registration 独立 fresh 原 workflow，须完整验证 frozen ten-field identity、原 binding_sha256、唯一原 observation entry、唯一 prepared ref 的 record / prepared / script / script_sha / args_sha 与原 binding。不得依当前 attempt、latest row、mutable result / failure payload 或文件存在推断归属。使用原记录的 owner / department / skill / date scope 和原 prepared 桥；当前 lease / claim 只用于标记 late，不是拒绝保存已发生原观察或授予业务写的条件。

精确 terminal duplicate（排除 registered_at）包括并发相同请求只登记一次、revision +1、Audit 一条；changed null / SHA / state / prepared / script / binding 均冲突拒绝，无补全升级。prepared、terminal 和 nested revision 均与 Audit 同事务原子保存。保留不超过 2000ms 的 lock_timeout，已有更严格值不得放宽；真实 row lock timeout / Audit INSERT 失败保留固定 `TerminalProcessRegistrationError` 与原 SQL cause，无部分提交。辅助事务不 commit / rollback / refresh 调用方 pending 或已 flush 的 unrelated DML。

late callback 只能在原 observation entry 追加 refs、增加 nested observation revision 和保存 system Audit；不得改新 entry、action row、workflow state / progress / updated_at、ar_execution / current_step / 新 plan、material / occupancy 或任何金融文件。使用 fresh context merge，调用方后续真实 success / failure transition 从其现有 fresh context 路径合并业务结果，不以 producer 前的 stale self.context 全量回写抹 refs。不能以捕获失败为理由修改 workflow_service 或 scheduler 的原生命周期。

Audit 沿用 `ar_process_prepared_registered` 与 `ar_process_terminal_registered`，只对 observation branch 加固定 `evidence_namespace="process_observations"`；`evidence_revision` 指该 nested revision。prepared 仍原 owner actor；terminal 仍 system actor、原 bounded identity、observation digest 与 late_observation。禁止 raw args、路径、stderr、财务行或凭据进入 Audit；effect Audit 结构保持。

### 5. 只读兼容与权限边界

本阶段不修改 F4.C effect-only history / details reader、公开 DTO、OpenAPI / TS 或前端。默认请求不触发 details；history 的 LiteralFalse、authorizes_resume false、原 effect attempt / unregistered / action 统计保持含义，observation entry 不算 registered effect 或 full-attempt coverage。新的观察分区仍不证明 whole-workflow 终止；其它 non-effect unanchored / 历史缺失保持 unknown。

metadata fingerprint 对原 workflow context 既有整体摘要逻辑继续有效：新增观察会令旧详情 token 过期，按现有刷新流程处理，不伪装 effect revision 增长或增加 UI 权限。GET 不创建、修复、补 SHA 或修改任何 DB / 文件。字段 null、缺 field、未登记与 known zero 保持现有不同语义。是否未来公开观察详情是另一期，不在本阶段偷偷扩大 reader 输出。

## Testing Decisions

### 最小 first red（设计审查后另行授权）

只新增一个独立真实 PostgreSQL / benign no-op integration test，复用 owned network-none container、tmpfs PG、独立 schema / 真实 ORM / permission / claim / lease 和原 native producer，不继承旧全部测试方法、不 mock constructor / gates / material checks / register / ORM。fixture 使用合成 workspace、合法四阶段 completed prefix、既有 checked plan bytes 与原 SHA、合成材料绑定；固定 Skill 目录中的唯一 build_worklist.py 为 benign 脚本，真实读取命令参数并向 --out 写合成非金融输出，stdout 可被原 worklist-summary 处理。它不调用真实财务脚本、外部 connector、生产连接或原财务文件。

通过实际 execute_phase → build_initial_report → ArExecution.script → Linux child 完成一条路径。Popen 外层仅保存启动瞬间独立 PG read-only snapshot，不替换原 gates 或 child；在实际 child cleanup / handler 成功返回之后才 assert 新 observation prepared / terminal ref 缺失。first red 必须是实际未保存原观察；计划/权限/缺参数/fixture/import/摘要准备错误不能称产品 red。早期快照随后证明 prepared commit ACK 先于 Popen；terminal 独立登记在调用方业务 transition 之前可见，原 effect entry / revision、占用与业务完成状态保持原值。一个新 case → actual red → 最小接线 → 同 case green，之后才逐个 core vertical。

### 核心反向（每次一个具体行为，实际运行留证）

1. 真实 prepared Audit INSERT failure / commit ACK loss：child 0、不可部分提交、callback 不 masking 原 SQL / gate error；ACK loss 不猜终止。
2. confirmed prepared 后 fresh 第二 fence / Popen deny：原 partial terminal nullable、取消/lease/permission/material/计划改变阻止新 spawn，不改业务完成或占用。各 gate 只复用必要既有反例，避免重复造一套 fixture。
3. actual no-op 后原 terminal Audit SQL constraint failure；真实 row lock conflict 与 stricter lock_timeout；caller pending / flushed unrelated DML 无 commit / rollback，原 prepared 保留、ref/revision/Audit 无部分提交。
4. exact duplicate 与 concurrent identical once；changed null/hash/state/binding 严格冲突。实际旧 producer cleanup 后受控 callback 内真实 claim2，原 refs 可 late 登记，新 action / context / business / material 逐项不变。
5. actual nonzero / timeout / cleanup 或 fact fsync / receipt 损坏的部分原 SHA 与原因链；复用原 validator 和真实已存在 receipt，禁止 mock 成功/失败返回及残存文件重算。不声称未实际运行的 hardkill 矩阵。
6. namespace 严格类型 / boundedness / duplicate / legacy absence，不从 mutable result / failure 或 latest attempt 反推；effect refs、effect revision、history / public unknown / default-off / readonly GET 原语义保持。验证真实业务 success 与 failure transition 均不以 stale context 丢独立 refs。

最终只跑本阶段新增 class 一次，无 skip；每个实际失败保留日志及性质，必要新 fix 后才合理 repeat。共享 gate / registrar 若改，针对性运行已冻结 F4.D 13 项；F4.C 选 default-off/owner 与 legacy/unavailable GET 两项（既有显式 legacy adapter，不删新 refs）；其余 F4.B 只选本阶段真实触及且未被上述覆盖的 gates / 非 effect 兼容反例。禁止默认收旧 21 / 全量 67；最终 root 根据实际依赖冻结具体 selector，不把历史测试次数折算为新覆盖。

### 完成标准与线上验收

设计审查通过、实际 first red / green、核心负例、最终冻结 hash / static diff 和独立 Spec / Standards 两轴 0 blocking 后，root 才推进后端-only build / release（若无前端或契约修改）。公开 OpenAPI 形状与生成 TS 保持、镜像源码 hash 完全匹配；保留已验收 F4.D rollback、Nextc3fb 与 balance.37。发布前 fresh runtime IDs / maintenance / 五类活动只读计数，等待安全窗口，不中断任务。

部署后 API / 两 Python Worker hash、health、normal 和邻接服务核对；owned 官方浏览器实际验证正常访问、default-off 请求数、显式 effect details / 原 unknown 与历史统计、旧 token 过期 / 刷新、只读说明及原控制按钮，无 business mutation / console error，官方 close 和 owned 临时清理。浏览器不创建/运行财务 action 来制造新观察；E1 精确 original process 行为由真实隔离 PG / no-op 留证，不能将只读浏览器 smoke 当生产金融业务验收。

## Out of Scope

所有其它 non-effect phase、独立 investigation、cache wrapper / cache builder / 后续 historyguard 的观察锚点；in-process flowplan / ledger / report / ZIP 写入锚点及金融结果判断；effect phase 增删、新材料占用、新权限、自动重试/恢复、full-workflow stop、admin resolve、no_effect_verified、解除 effect 占用；全 hardkill 矩阵、F5 发布崩溃协议、通用任务框架、SQL 表 / 锁服务；公开 observation DTO / 前端详情扩展。E1 不是 full-attempt complete、F4 完成或全计划验收。

## Further Notes

原施工标准 CW06 / F4、ADR 0003 与当前领域 / issue 约束继续适用。F4.D accepted 是本阶段先决条件；issue 01 唯一纵切，root design review 是下一授权边界。必要产品接线仅现有 safety 与 runner 模块；producer / F4.C reader / lifecycle service / scheduler / cache / business Skill 保持，若实际 red 证明需要扩大已限定接口，先显性报告 root，不能以规格推导自行扩大修改。

本规格由当前授权与已核实源码合成，无新金融业务判定问题；尚待 root 审核 nested 分区 / revision 与小接口设计、首红 fixture / selector、后续每条 core 实际覆盖清单。源码、测试、审查、构建、部署、runtime、浏览器和金融业务验证分别记录；当前仅文档，未实施、未测试、未发布 E1。
