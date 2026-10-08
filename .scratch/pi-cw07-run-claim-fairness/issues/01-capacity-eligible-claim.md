# 01：普通 Run 候选按当前容量过滤

Status: ready-for-agent
Type: task
Blocked by: none
Date: 2026-10-08

## 问题

前100个 queued Run 都达到各自 Skill 并发上限时，现有固定前100领取会重复跳过它们，第101个独立可执行任务永久不可见。

## 实施合同

[spec.md](../spec.md) 为本 ticket 唯一规则来源。实施容量 grouped SQL 预过滤、原100候选上限、只包候选SELECT的PostgreSQL事务局部2s超时及聚合观测；保留原锁顺序、NULL租约unknown计数、逐Run固定上限和所有领取guard。

先核实实际持久源码、运行镜像、活动任务与已有差异；在远程修改授权产品文件及必要专项测试，保留无关修改。保持一次候选列表，Worker loop 无新游标，数据库无新字段/表。与 F1、AR balance.37、A25维护、F3重试分开交付。

## 完成标准

spec 的9组针对性条件全部有证据，真实隔离PostgreSQL未跳过；第101个独立可执行任务一次领取，前100个未知/满额占用未释放。预算、query timeout恢复、自然推进及竞争均得到实际结果。专项审查无阻断问题，适用构建通过。

由根代理按AGENTS.md完成必要部署、运行哈希/健康核验及浏览器只读验收，明确源码、验证与上线状态。仅写完代码或文档不关闭此ticket；不能凭F2声明整个CW07完成。

## Comments

- 2026-10-08：规格与ticket准备完成；产品未修改，专项未运行，未部署。根代理将继续实施。


## Completion 2026-10-08

F2 source, targeted verification, production deployment and read-only browser acceptance completed; see [release evidence](../../../docs/pi-cw07-run-claim-capacity-20261008.md). No commit, push or financial task. Overall construction continues with F4.A.
