# 应收核销执行链核查

证据范围：远程重构工作树当前源码。此记录不证明生产容器使用同一版本，也不证明业务验收完成。逐文件 SHA-256 和函数范围见 reports/ar-execution-chain.json。

## 入口和分流

`main.new_workflow` 的 POST /api/workflows 调用 `workflow_service.create_workflow`，后者提交新任务。Pi 工具入口为 `routers/pi_harness.request_pi_harness_tool`；先校验当前 Harness 动作及租约，再调用 `queue_pi_harness_tool`。属于 TOOL_PHASE 的工具进入 `ar_execution_runner.queue_execution_phase`。这些是不同职责的入口，不能把 Agent 工具调用当作直接写表。

准备工作流在 workflow_service.py:6131 通过 execution_version(workflow) 分流：固定新版契约时调用 initialize_execution；否则继续旧版计划构建。执行器在 workflow_service.py:7657 对 ar_ 动作调用 execute_phase 与 transition_phase；其他动作仍走各自旧分支。_apply_confirmed 仍存在，不可依据新版阶段测试就删除它。

## 领取和执行

worker.run_once 先领取普通 Run；没有普通任务时调用 run_workflow_action_once，显式传递当前 CONTRACT_VERSION。工作流领取器要求 workflow 池，使用领取锁，排除 PI_HARNESS_ACTION，检查工作流状态、并发和所有者权限，设置 worker/attempt/heartbeat/lease 后提交。run_workflow_action_once 用 LeaseHeartbeat 包围执行；租约丢失标记阻止正常收尾，否则清除租约并提交。

execute_phase 先锁定动作，检查取消、阶段前缀和输入材料绑定，提交当前阶段状态并清除锁缓存，再执行 ArExecution 对应方法。缺少阶段方法直接失败，不回退旧流程。执行结果返回完成阶段列表及下一工具，由 transition_phase 处理状态迁移。脚本执行和阶段结果持久化不是单个数据库事务。

## 新版阶段顺序

inspect_materials → classify_receipts → review_order_evidence → validate_reconciliation → build_initial_report → stage_reconciliation → write_ledger → write_receipt_flow → verify_reconciliation → rescan_holds → build_final_report → review_final_report → publish_reconciliation → complete_reconciliation。

ar_execution_contract.next_phase 只接受上述顺序的连续完整前缀。write_ledger 和 write_receipt_flow 标为工作簿修改阶段；暂存与发布同样属于受保护工具。源工作簿、暂存工作簿、平台文件登记、材料版本及正式辅助台账需要分别验证。

## 发布与事务边界

publish_reconciliation 验证暂存指纹、最终结果指纹、输入材料绑定及取消状态。在 savepoint 内登记材料和报告，再调用 _publish_verified_material_set；异常走文件登记清理。返回 publication=verified 之前不代表 complete_reconciliation 已执行。

_publish_verified_material_set 自身使用 savepoint，调用 publish_workflow_material_set，再回读至少一份年度表和唯一流转表；提供年度映射时逐文件比对年份。publish_workflow_material_set 将固定 material_set_id 作为 expected_current_id 交给 create_or_replace_current_set。savepoint 不是最外层提交，必须继续追踪调用方提交与文件系统副作用。

complete_reconciliation 只接受 verified 发布状态，生成 publication manifest 并提交，再运行 complete_execution.py；验证生成的正式台账 schema、发布引用及暂存指纹后返回台账候选。该阶段允许出现材料已发布但正式台账尚未完成的中间状态；publication_needs_completion 显式识别此状态。重构不能将其混同为未写入，也不能自动重复财务写入。

## 尚需验证

以上是已逐段检查的源代码关系。材料版本原子切换细节、文件清理失败补偿、异常事务调用链、前端入口到 BFF、Pi 模型执行端和生产镜像哈希对应关系仍需补充证据。不会把静态链路图计为运行 E2E 通过。
