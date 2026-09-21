# PR-04 停用账号 Workflow 管理员停止

## 实现

新增单日及批次管理员停止API：/api/admin/workflows/{workflow_id}/stop-disabled-owner 与 /api/admin/workflow-batches/{batch_id}/stop-disabled-owner。调用当前实际管理员，锁后检查账号、固定部门、owner当前部门及disabled状态。普通取消仍owner-only。共用原有取消迁移、整批取消及原子写入/发布完成保护，不新增强制kill或财务重跑。

batch取消分为不提交核心及普通公开提交wrapper；管理员单日/批次状态、原取消审计和新增workflow.admin_stop_disabled_owner审计在同一最终事务提交。失败任务的queued/running调查保留原失败记录并申请停止。

## 验证

226项专项通过：原授权/取消兼容，加14个单日/批次管理员矩阵、4个终态调查和1个双路由匿名拒绝。批次正例含第二个未执行日期；最终管理员审计故障独立注入，断言原取消审计与状态均回滚。初次匿名路由测试误启用全局app lifespan导致测试默认库未迁移，改为不启动生命周期的路由测试，继续以隔离Session验证请求依赖。

OpenAPI导出和TypeScript契约生成/一致性检查通过；只增加生成类型，无前端UI改动，本轮不重建前端。候选与受限恢复镜像独立数据库schema、事务、恢复政策检查通过；236个AR文件哈希完整保留。

Standards审查未发现当前源码确定缺陷，但未完成其固定镜像对比；Spec审查已完成固定00c80源码对比，未发现确定回归，提出的终态调查、多日期、最终审计失败验证已补齐。锁等待期间owner重新启用/换部门的专门并发组合仍待补，不声称全部PR04阶段验收完成。

## 发布

保留另一会话71734b3e1f86的12个AR变动，完整236文件；候选34623fa49afc，恢复2f6c56d41385。发布已成功，三个后端各199+236文件哈希匹配，UID10001、restart0、DB f3、normal；两个新增路由实际HTTP匿名请求均401。证据见deployment.json及runtime-verified.json。没有修改看板、提交推送、真实核销或账号状态。

## 实际锁等待补充验收

232项专项通过。新增6项单日/批次实际PostgreSQL调度锁竞争：持锁期间owner恢复active、owner换部门、管理员降权；请求保留旧ORM实例，释放锁后分别409/404/404拒绝，任务仍queued且无审计落库。管理员降权404来自既有资源隐藏策略，保留此策略。此前“锁等待期间身份变更未验证”的缺口按这些组合补齐。

证据PR-04-admin-stop-lock-wait-tests.json；本轮只测试和文档，不构建或重启服务。完整执行快照仍有原始消息绑定缺口，已定位共享persist_run入口与可信历史PreparedPayload来源，见PR-04-execution-snapshot-scope.md；尚未实现新快照存储或迁移。
