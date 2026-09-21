# PR-04 已发布依据的当前登记核验

## 证据与修复

检查撤权后必要收尾的可信依据时，发现 publication_manifest 用 db.get 读取已被 Session 缓存的材料及文件，材料.files 也可能保留旧成员。真实隔离 PostgreSQL 回归复现五类失检：材料部门变化、成员摘要变化、成员删除、文件部门变化、文件登记摘要变化。已有文件字节校验能拦截磁盘内容变化，不能代替当前登记核验。

现在材料与其成员通过 select/selectinload/populate_existing 重新读取；工作簿和正式报告的 FileRecord 同样刷新。沿用固定归属、日期、Skill、成员、摘要和文件字节检查，不新增必须为current材料的限制，不修改财务脚本，也不绕过现有身份/Skill权限。事务仍由调用方负责，没有新增commit。

## 验证与发布

39项PG测试通过：原24项审批、4项发布后取消，加11项发布依据和正式报告缓存回归。覆盖历史superseded材料成功、有效材料成功、另一事务修改以及文件字节变化。所有文件均为隔离合成数据；这些用例不代表真实核销、写表、回读全链路验收。

规格与规范独立审查未发现确定缺陷；补充了明确的历史非当前材料成功用例。静态diff检查、候选与恢复镜像迁移/事务/回放限制检查通过，各442项后端及AR文件哈希一致。部署和运行证据分别见 PR-04-publication-current-evidence-deployment.json、runtime-verified.json。未提交推送，无真实财务操作，无看板操作。

## 撤权收尾仍待实现

complete_reconciliation目前仍调用任务固定Skill中的complete_execution.py，其职责是生成辅助台账候选，后续由平台登记。不能仅凭动作名称取消权限检查后执行任意固定Skill代码。后续须界定系统受限收尾所信任的已发布证据、租约和允许的输出，保留工作簿禁止再写和不得启动下一日期的约束。此次只修复其中的当前登记依据缺口，未实现撤权豁免，不标PR-04完成。


2026-09-20 08:34 UTC：已发布依据当前登记核验切片已上线，镜像0d1a589a0110，恢复镜像518da2aa608b；39项专项通过。三个后端各442项哈希一致、UID10001/restart0/DB f4/replay_only=false，平台normal。240项AR文件保持不变。只解决发布回读的陈旧材料/成员/文件登记问题，没有放宽撤权检查；受限系统收尾与阶段授权审计仍未完成。证据见reports/PR-04-publication-current-evidence.md及runtime-verified.json。
