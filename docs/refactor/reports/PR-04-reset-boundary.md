# PR-04 重置入口身份、状态与审计

## 问题与源码

reset_workflow 原先取得调度锁后沿用旧 Workflow 对象，并只检查固定任务 owner，不检查实际 actor。真实数据库用例复现旧管理员身份、其他用户、跨部门管理员和陈旧阶段能够重置任务。

backend/app/workflow_service.py 现在按 global锁、刷新任务、当前实际actor权限、固定owner资格、执行中动作检查的顺序操作。复用 execution_actor(CONFIRM)，不扩大管理员跨部门权限。成功重置追加 workflow.reset 审计，使用当前实际actor，与任务修改同一事务提交。

## 验证

backend/tests/test_execution_authorization.py 新增9项真实数据库测试，旧代码4项失败；修复后165项专项通过。覆盖账号/权限/部门变化、角色降级、其他用户、跨部门管理员、阶段已转为applying，以及合法owner和同部门管理员。拒绝时日期、文件绑定、上下文和消息不变，成功时审计actor一致。静态diff和双轴审查通过。

候选0a59d4d46913、受限恢复998a5d888924通过隔离PG迁移、重复迁移、只读角色及事务检查，完整保留213个AR Skill文件。恢复镜像保留权限门槛，只允许已绑定回执重放。无DB结构修改。

## 发布及未完成范围

以5d2fd766b857为基础构建；发布前两次核对三个后端基础镜像一致，normal、活动零。实际发布/回读见PR-04-reset-boundary-deployment.json与PR-04-reset-boundary-runtime-verified.json。

取数确认、补取及其审计事务尚未修改，调用证据见PR-04-material-entry-audit.md；PR-04及完整方案未完成。未执行真实重置、核销、补取或财务写入，未提交推送，看板未操作。

2026-09-20 06:39 UTC 发布退出0并完成回读：三个后端0a59d4d46913，各199后端+213AR文件哈希一致、UID10001、restart0、DB唯一f3、非replay-only、normal、五类活动零。
