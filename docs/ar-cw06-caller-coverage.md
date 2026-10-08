# CW-06 应收核销执行入口覆盖表（施工中）

观察日期：2026-09-29。源码为远程持久化工作树 `refactor-worktrees/full-platform-20260918`；本轮线上 API 与两个 Python Worker 的镜像为 `sha256:9586fa550b5608b0d95ddd859c9e136b793034aa0f01e38d1463b4915e9161d0`，其中 `backend/app/workflow_service.py` 的 SHA-256 为 `24655bf102dd5cf1a58db52c0a4e05f3a9ac303c099525d3ea1ea0f06279a4d9`。本表记录实际调用链及证据强度，不能代替最终安全签收。

| 入口 | 实际调用路径与当前保护 | 验证证据 | 状态与剩余工作 |
|---|---|---|---|
| 网页新建单日 | `main.start_workflow_session` → `workflow_service.start_workflow` → 领取全局调度锁、权限/材料校验、`_assert_current_ar_material_clear` → 入库与初始动作。旧对话入口 `main.new_workflow` → `create_workflow` 也调用同一占用检查。 | 读取两条路由和三个 service 入口；本轮未提交生产创建请求。 | 入口已接线；仍需与统一操作决策合同及提交失败竞态测试对齐。 |
| 网页新建多日 | `main.start_workflow_batch_session` → `start_workflow_batch` → 全局调度锁、`_assert_current_ar_material_clear`；逐日任务按序执行。 | 读取路由与 service；本轮只读浏览器确认创建页加载、当前材料和“开始任务”未启用，未选日期或启动任务。 | 入口已接线；批次和单日的同事务占用断言仍需系统化测试。 |
| AI 助手建批次 | `assistant_workflow_service` 的待启动计划调用 `start_workflow_batch`，启动前还重读材料指纹和任务状态；不存在独立的财务写入实现。 | 读取 `assistant_workflow_service` 的真实调用段。 | 复用业务入口；HTTP 响应丢失与计划并发仍待专门回归。 |
| Pi Harness 派发阶段 | `routers/pi_harness.py` → `workflow_service.queue_pi_harness_tool`，刷新租约、所有者和权限；仅对其他工作流检查材料占用；阶段工具再经 `ar_execution_runner.queue_execution_phase` 校验固定参数、计划指纹与材料版本。 | `test_ar_postpublish_occupancy.py` 的本任务发布后继续、其他任务仍阻断两项隔离回归；2026-09-29 线上容器内存回归 6/6。 | 本任务自占用修复已上线；尚无统一 `assert_operation_allowed` 合同。 |
| Worker 领取与执行前 | `worker.py` → `run_workflow_action_once` → `claim_next_workflow_action` 校验固定契约、所有者权限和领取代次；`ar_execution_runner.execute_phase` 在实际阶段开始前调用 `verify_input_binding`，持久化副作用意图。Pi 领取另由 `routers/pi_harness.claim_pi_harness_work` 处理。 | 已沿调用链读取 claim、execute、binding；本轮未故障注入真实 Worker。 | 局部保护存在；需要覆盖 Claim/执行之间的身份、版本变化和所有执行来源。 |
| 日期切换与失败批次继续 | 正常下一天由 `transition_phase` 在正式台账登记后调用 `_advance_batch`；网页 `/api/workflow-batches/{id}/retry` → `retry_workflow_batch`。失败日期的可重试前写阶段现于排队前调用 `_assert_current_ar_material_clear`；范围报告的只读恢复不因本门禁阻断。 | 新回归在旧镜像实际越过占用门禁并走到重新排队；候选与线上容器内存回归通过，跨任务占用返回 409；无真实批次重试。 | 本次漏口已上线；补取与所有批次恢复分支还需逐项证明。 |
| 材料上传、替换和恢复 | 实际文件上传/删除路由与 `update_workflow_files`、`restore_material_set` 使用 `workflow_material_lock.assert_material_editable`；其 `material_edit_state` 把活动批次、单日动作及当前材料未解决写入计入锁定。候选文件“移除”路由只在审计中隐藏可选项，不改变当前材料绑定。 | 已读取 `main.py`、`workflow_material_service.py`、`workflow_material_lock.py` 和 `ar_material_candidates.py` 调用段；共享路径合成回归 2/2。 | 当前版本、文件身份和跨别名锁在所有实际材料变更入口仍需矩阵验收。 |
| 显式阶段恢复 | `/api/workflows/{id}/execution/recover` → `ar_execution_recovery.recover_execution` → `recovery_status`、固定检查点和 `ArExecution.verify_input_binding`，失败写入阶段不盲目重派。 | 已读取路由和恢复实现；本轮未执行真实恢复。 | 保护存在但尚未达到 CW-05 的三轴统一事实/操作合同。 |
| 发布与正式登记 | `ArExecution.publish_reconciliation` 重核权限/输入绑定，`_publish_verified_material_set` 发布材料；`transition_phase` 对 `complete_reconciliation` 候选进行回读、复制与正式台账登记，之后才使日期成功并推进批次。 | 已读取实际阶段与过渡路径；本轮未发布或写入任何财务材料。相关 pytest 用例存在但候选镜像无 pytest，本轮未运行。 | 仍需完整崩溃窗口、丢失提交响应与旧 attempt 竞态证据。 |
| 管理员停止、调查、解除占用 | `main.py` 的管理员停用所有者路由走 `stop_disabled_owner_workflow`；未发布结果的放弃走 `ar_abandon.abandon`。 | 路由与函数引用已定位；`test_ar_abandon.py` 隔离回归 12/12。 | 尚无统一、带版本与证据摘要的 `admin_resolve` 条件更新入口；不能把停止等同于解除占用。 |
| 租约过期、清理与发布排空 | `worker.py`、Pi 领取和普通 Worker 领取均触发 `scheduler.recover_expired_jobs`；AR 缺进程退出证据时保留不可领取占用，已核实退出也不自动重试写入。受控部署排空目前检查活动计数并维护模式切换。 | 已读取实际调度调用点；本轮上线前后活动计数均为 0、maintenance 为 normal。 | 活动计数不等于未解决占用全集；发布排空和清理须纳入 `needs_investigation`，不能据此宣称 CW-06 完成。 |

当前尚缺的总门禁：一个只读、明确区分 `process_state`、`effect_state`、`occupancy_state` 的 `get_safety_view()`，以及在持锁事务中统一复核的 `assert_operation_allowed()`；现有实现仍由各入口组合 `current_material_blocker`、材料锁、阶段恢复与发布检查。下一轮先完成所有入口的共同决策表及调用者测试，再评估是否需要最小占用迁移。此表不把本轮 20 项隔离测试扩大解释为整个 CW-05/06 已通过。


## 2026-09-29 09:28 · CW-05 执行意图完整性校验上线

- 在统一三轴投影之前补齐其证据基础：安全索引读取核验任务、动作、次数、阶段、执行者、材料等绑定及 SHA-256；未知状态、绑定损坏或完成事实不全按未核清处理。完成登记还须匹配启动意图的任务和 Worker，不能把其他执行者的结果登记到原记录。摘要只校验一致性，不充当权限凭据。
- 新增 `backend/tests/test_ar_safety_integrity.py`，旧线上镜像在 10 项中失败 7 项；修正后 10 项全部通过。候选镜像共 30 项相关 unittest 通过，包含发布收尾、共享路径材料及放弃未发布结果。只读审查 670 条工作流，其中 46 条含安全索引，新增校验无不兼容记录。没有做全量测试或真实核销。
- 持久化源码 `backend/app/ar_execution_safety.py` SHA-256：`c392d1d0a4019af8bf41a8f4f44daea85811d900e7d921d9d8d712eda706d65d`。只在现场运行镜像 `sha256:9a213ce2c5cae52eedf96361b8d4aab83cd15e38282e51585e5490aa605ee88e` 上替换此模块，未覆盖其他会话修改。
- API、标准 Worker、任务检查 Worker 已切至 `sha256:c20e27e3aeb16d9e0e8cd6571238aee3a40fbce3eca0429882e63da936a0bc7e`。独立回读三容器镜像/文件哈希一致，API healthy、模式 normal、活动任务 0。回滚配置：`/home/lee/financial-platform-isolated/releases/managed-20260929-012654-ea1b74ed`。
- Chrome 在上线后重新加载核销创建页，当前材料 V390 与最近任务正常，未选日期时开始任务禁用，浏览器错误日志为空。未启动或重试业务任务、未改业务工作簿、未提交推送。
- 本轮只补强现有安全事实校验。`get_safety_view()` 三轴投影、持锁的 `assert_operation_allowed()`、全入口合同和完整崩溃矩阵仍未完成，不能将本轮通过等同 CW-05/06 完成。


## 2026-09-29 · CW-05/06 材料查询与事务内准入统一

新增 `ar_execution_safety.get_safety_view()` 作为只读材料占用投影，`assert_operation_allowed()` 作为操作前的加锁复核入口。后者先取得现有调度锁、flush 当前事务，再按数据库列值重新查询，不接受 UI 判断、force 或客户端进程退出布尔值；不自行 commit。调用者仍负责权限、阶段/版本检查及最终提交，不得持此锁等待长脚本。

已接线：网页/Agent 共用的新建、旧失败任务重建、Pi Harness 续接、失败批次的前写继续，以及实际材料替换、删除前保护和恢复入口。材料页面读取和材料变更使用同一规则及消息。新建、材料变更、跨日期继续不接受排除旧任务；同任务续接可排除自身，其他任务占用仍有效。原有 single-flight 和恢复阶段限制保留。

当前投影合同是 `ar-material-safety-view-v1`，不是整个执行域已认证的三轴合同：`occupancy_state` 为 free/held/needs_investigation，阻塞任务的 `execution` 单独描述持久化 effect_state；没有做实时完整执行域观察时 process_state 明确为 unknown、process_evidence_scope 为 not_observed。没有选中阻塞任务时 execution=null，不伪造 not_started_verified。material_admission_allowed 只表示本材料占用检查通过，不构成业务操作授权。页面仍保留原 locked/reason 格式，未新增未经验证的操作按钮。

数据库查询改用列投影，避免 ORM identity map 中旧工作流、材料关联及动作状态影响判断；只读查询不 autoflush、不覆盖调用者未提交字段。超过工作流或动作扫描上限继续拒绝冲突操作。

验证：9 项新接口测试通过；候选镜像相关 unittest 共 47 项，46 通过，1 项既有本地工作簿测试按环境条件跳过。另用无外网、无生产挂载、数据库完全位于 tmpfs 的独立 PostgreSQL 验证并发：第二事务等待持锁写事务，提交后即使缓存旧 WorkflowSession 也读取新占用并拒绝。该测试 1/1 通过，临时容器已全部移除。现行两组当前材料只读比较，新旧 blocker 和编辑锁判断均无差异。未执行全量测试、真实任务或生产故障注入。

源码及运行文件：

- `ar_execution_safety.py`：`1756310dc7f539cd6b86f5a991139caab50c144b948703750def887620519631`
- `workflow_service.py`：`3e1a4f63bd45851badfd34a1edb0fb4619324641c9df81ce064669e796146893`
- `workflow_material_lock.py`：`5b6587e9efce03b1f7304b26876220c6900eb3a0b1f6a24486adaa9bbbefeb5b`

候选由当时现场镜像 `sha256:26dde408fbc8cce4c38820bb06cdb2e1307f4218b79447e99fd0ca96d981c296` 离线叠加以上三个文件，保留其他会话的业务修复。部署后 API/两 Worker 镜像为 `sha256:640994eba7c4ef27a67dab5cd2d39e5a62f72151ee268d58c3523f8ae86312cf`。

部署回滚配置为 `/home/lee/financial-platform-isolated/releases/managed-20260929-060215-0d5a4d3c`。独立回读三个容器及持久化源码的三份文件哈希一致，API healthy、服务运行、维护 normal。Chrome 上线后刷新创建核销页面，材料状态查询完成，V390 两份选用材料与材料操作入口正常，未选日期的开始任务仍禁用，浏览器错误日志为空。没有操作真实任务或修改材料，未提交推送。

剩余边界：Worker 领取、脚本执行前、发布、正式登记和管理员处置尚未全部改用新的持锁入口；其中现有执行/发布路径仍使用同模块 current_material_blocker 和原执行约束。完整进程域、所有 attempt 历史未决项、发布崩溃窗口与前端调查动作仍需完成。不能将本轮视为 CW-05/06 或整体改造完成。


## 2026-09-29 14:15 · Worker 领取也复核材料占用

`claim_next_workflow_action` 在固定契约和所有者权限校验之后、动作进入 running 和增加 attempt 之前，调用共同 `assert_operation_allowed(operation="claim_action")`。其他任务存在未核清占用时保留 queued、attempt/worker/started_at 不变，显示“等待材料占用核清，此步骤尚未开始”，继续考察后面的独立任务；不是对已执行财务步骤进行重试。调查和最终范围报告保留可执行入口。同任务已发布后正式登记允许排除自身占用，不能排除其他任务。

新增领取回归在旧镜像 5 项中复现 3 项失败。最终 6 项覆盖冲突步骤不领取、不消耗次数、无关 owner 不饥饿、自身收尾、取消标签不释放占用，以及其他任务有占用时调查与范围报告仍可领取。候选整组 52 项 unittest 为 51 通过、1 项既有工作簿测试跳过；随后补充报告分支并将调查测试加强后，6 项领取专项通过。独立 PostgreSQL 并发测试还覆盖实际服务端领取游标在阻塞候选之后继续选取独立任务，1/1 通过；临时数据库在 tmpfs，无生产挂载或外网，容器清理已核验。

`workflow_service.py` 最新 SHA-256：`97846bdf34c30f33e5b6c899315f228976a842b77b8b911a466357b6c30acd21`。本段镜像为 `sha256:2d9d232fca9c8f72c91720718658cc61e6513a81fdd197f3c97c6489b85587a1`，回滚配置 `/home/lee/financial-platform-isolated/releases/managed-20260929-061100-1af21dc6`。

独立回读期间标准 Worker 短暂退出，随后线上接续切到另一业务镜像 `sha256:86e92b6d02eb95048788260b929938dd6e977a8cc3832382d045ca4b5978fac8`。重新核查 API/两 Worker 均运行该镜像，三个安全模块与持久化源码哈希一致，API healthy、维护 normal、活动任务 0；没有回滚覆盖接续发布。新镜像的 15 项材料策略及领取核心用例复测通过。Chrome 再刷新显示业务 Skill balance.28、当前材料 V390，材料状态加载完成，开始任务未选日期仍禁用，错误日志为空。

没有启动、重跑或改写真实财务任务/工作簿，未提交推送。Worker 领取入口已接共同准入；完整进程域证据、执行前/发布事务的统一复核、正式登记与管理员处置仍保留后续工作，整体施工尚未完成。


## 2026-09-29 执行、发布和正式登记接入共同材料准入

`ArExecution._verify_material_binding` 在原任务材料身份检查内调用共同持锁接口；普通脚本为 resume_phase，发布为 publish，完成登记为 complete_registration。调用方原有租约、当前授权、计划/文件校验不变；共同接口不提交事务，长脚本仍在调用方提交释放锁之后启动，发布与登记仍随 Worker 完成状态原子提交。queue_execution_phase 的排队前复核也改用共同接口，冲突保持 HTTP 409。显式恢复 recover_execution 和关联采纳 ar_recovery_adoption._fence 通过 verify_input_binding 复用本次接口。

保留原有限定例外：已发布的历史材料与当前材料不同、完成阶段且 stop_after_action=true 时，必须核验原 publication_manifest，只登记原发布结果，不通过当前材料准入启动新写入或推进批次。本次没有放宽异常路径。

新增6项边界测试（含参数子项），验证共同接口接线、领取后新增冲突、guard 不提前提交、历史收尾必须有发布证明、非收尾/未要求停止不能沿用历史材料，以及派发冲突不排队。候选和实际线上镜像均运行27项相关 unittest，全通过；静态 diff 已审阅。未执行真实财务任务和全量测试。

持久化 runner SHA-256：25b5a207079969dc81f09a46ece90f565290ba116fa10562693ca56314df87f9。独立候选为 sha256:5304068fd3a96c4683341e6c430d9c7b8cc330bb829547c3c1ecc82e7589a3c8。本会话发布因另一发布持锁而在切换前退出，没有强行覆盖。随后另一业务发布镜像 sha256:01fa0d313e4bb5d761dc2884e8bca13812949b1ea684b2ff7e02929d1440f8cf 已包含本次 runner；独立核对 API/两 Worker 的四个共同安全模块与持久化源码哈希一致，API healthy，维护 normal，活动任务0，因此没有再次冗余重启。

Chrome 只读验收创建页：Skill balance.29、材料V390、状态查询结束、两份材料正常、未选择日期时开始禁用，浏览器错误日志为空。没有更换材料或启动任务。

仍未完成：完整执行域/后代进程停止证明、历史多 attempt 的全入口调查、管理员处置统一规则和发布崩溃矩阵。现有进程核验主要证明直接子进程退出，不能称为完整进程域已停止。


## 2026-09-29 14:38 Linux 后代进程监督与失效执行占用验收

新增 ar_process_supervisor.py，在启动受控脚本前设置 PR_SET_CHILD_SUBREAPER。主脚本退出后继续 waitpid 所有子孙进程，包括 setsid 和双重派生的孤儿，直到内核报告无剩余子进程，再以本次随机绑定值写入独立退出凭据。原调用的 stdout/stderr、返回码及 Skill 路径约束保留。不存在凭据、版本未知、绑定不符、超时或监督进程被终止时，不将直接子进程退出等同完整退出；不登记阶段成功。

run_recorded_script 的 Linux 路径启用监督层；ar_process_inspection 对新声明执行域的记录同时检查 prepared/started/exited 绑定和 domain-exited 凭据。查询会说明 linux_descendant_tree、partial_descendant_tree 或 direct_children_only；外部服务和无关应用不在证明范围。旧证据仍按旧合同读取，不伪造新的后代退出事实。当前共同材料投影仍保守标记未实时观察的 process_state=unknown，没有由子进程退出直接推导无业务副作用。

10项实际子进程测试在隔离容器 tmpfs 中通过：正常输出、脱离进程组后继续写、双重派生、超时、启动日志写入失败、超时后脱离子进程继续写、凭据缺失/篡改、脚本错误返回、未知执行域版本。加上27项共同准入与Worker领取回归、22项封存/证据完整性回归，本阶段分组59项通过。另1项端到端合成场景通过：持久化写入意图后启动真实脱离子进程，主脚本结束但子进程仍写时将动作租约设为过期并标 failed；共同新建/换材料/跨日准入均拒绝，真实 claim 函数不领取第二写入、不消耗 attempt；子进程退出后未核查业务效果仍保留占用。总计60项不同测试通过；未做全量测试、真实核销、生产故障注入。

静态 diff 已审阅，源码直接远程修改。API/两 Worker 已受控部署 sha256:7deb79dcf90b8d446e0ac12a48f5a847c5e8b1b2fee99c6aa4e98c885cb2a589，独立回读7个相关模块哈希一致，API healthy、维护normal、活动任务0。回滚配置 /home/lee/financial-platform-isolated/releases/managed-20260929-063720-ae071786。Chrome刷新后材料查询完成，Skill balance.29、V390、选用材料和最近任务正常，开始按钮未选日期禁用，错误日志为空。

源文件SHA-256：ar_process_supervisor.py=18d59c8703633e048da90197b38526c941150b0e8e52bf4a20334ea597548b64；ar_process_evidence.py=f2ee344552d53dbd34eeac7b049b32ad5cc4207da1c15907fe57a3484ab15d90；ar_process_inspection.py=3ca4d0bd195adb6057f76cf6bf3e1161e09c16fdb436e0696cfea91b251a97cb。

边界仍保留：旧记录只有直接子进程证明；监督层被终止时脱离进程组的后代可能仍活着，此时保持unknown占用，不盲目杀进程、不自动重派。未声明的外部应用和外部写入不能据此认定安全。全入口管理员处置、发布提交响应丢失、历史attempt调查以及CW01等剩余矩阵尚未全部完成。


## 2026-09-29 完成登记凭据复查：已验证，等待活动批次结束后发布

正式登记现在在登记成果之前重读后代退出凭据，检查SHA-256、监督进程身份、随机绑定值、版本及脚本退出码。有效所有者与授权被撤销后的已完成登记走同一凭据检查，不能只信任内存中的退出标记。ar_process_evidence原有乱码提示一并恢复中文。候选为sha256:d8d91be4b5bcc8b48f9b009d71d29eaf155e6803b28be2863f10e1b35eed6dcb，尚未上线；当前真实批次仍运行，未切换服务。

修正旧测试缺失的持久化effect intent及原材料版本夹具。四项并发授权撤销场景改在独立PostgreSQL运行，避免SQLite整库写锁冒充生产故障。完成授权模块67项与发布证据11项在候选镜像的隔离PostgreSQL验证：首组75项通过，最后3项因测试库256MB tmpfs的WAL耗尽而setup失败；换全新隔离库重跑这3项全部通过。分组共78项通过，不是一次78项全绿。新增场景包含凭据缺失、SHA不符、token不符、错误返回码，以及有效/撤销所有者的真实登记入口。无生产库连接或真实核销写入，临时容器与网络均清理。

另3项发布重复请求测试通过：已提交响应丢失后，新事务中的重复请求返回原成功动作，不派发第二次发布；固定输入改变及已提交动作丢失分别拒绝。此测试调用真实queue_execution_phase和共同数据库准入，替换了环境租约及外部派发依赖，不代表所有真实文件发布崩溃窗口已经验收。

待部署源码：ar_process_evidence.py=33bcc5b08b41452c18a2a557795b8d73ff8aa5b8878821f567c8bdc243734a94；ar_completion_authorization.py=9b15cb86e95ee11d3dccc5377854c7d09efb3b776c3ecdba9ad810eb2b799b46；ar_execution_runner.py=98926aa2f3052d0fd744f272c61e3d4e0dc3958516b798bea66403a553f387ba。


### 上述完成登记补丁于 2026-09-29 15:26 生效

现有31天批次正常结束、活动计数归零后，受控切换API与两个Worker到候选d8d91be4b5bcc8b48f9b009d71d29eaf155e6803b28be2863f10e1b35eed6dcb。回滚配置为/home/lee/financial-platform-isolated/releases/managed-20260929-072440-db85ee64。独立回读三个容器，8个相关模块均与持久化源码一致，API healthy，Worker running，维护状态恢复normal。浏览器只读验收：原批次显示31天完成，材料V432的状态加载正常，材料锁已随原批次结束解除，未选日期的开始任务禁用，错误日志为空。没有启动、重跑任何财务任务，也没有将原批次作为新补丁的业务回归证据；该批次在切换前完成。
