# CW07 / F2：普通任务按可用容量领取

2026-10-08 已完成源码、针对性验证、上线和只读浏览器验收。仅完成 F2/A24；整体施工继续，A25 维护任务延后控制及其他阶段仍未完成。

## 行为

Worker 从整个 queued 队列先按每条任务固定的并发上限筛出有容量的任务，再取最早 100 条。前 100 条被满额 Skill 占据时，后面的独立可执行任务不再被永久遮挡。所有 owner/pool 的 running 均计入，NULL lease 和过期恢复后的 NULL lease 仍占容量。

原 scheduler 锁、材料固定快照、权限、确认、attempt、事件和提交检查保留；没有新增表、扩大候选数量或执行财务适配器。SQL 只缩小候选集合，不授予执行权限。满额 Skill 的坏 manifest 会等容量恢复后才报告失败，此提示时机变化已验证。

候选 SELECT 在 PostgreSQL 中使用事务局部最多 2 秒的 statement_timeout，已有更严格限制保留；正常查询后先恢复，再做原检查。超时、查询异常和提交失败必须传播并回滚，不能解释为无任务。LIMIT 100 不保证整个 SQL 扫描成本恒定。新增日志只含聚合计数、耗时与固定结果分类，无任务身份、路径、金额、SQL 或异常原文；正常空队列及满额轮询静默。

## 验证

- 保留两次真实 red/green 和负面 fixture 记录。真实隔离 PostgreSQL 最终 11 passed in 5.14s，0 skip；规格 9 组覆盖齐全。
- 两 Session 争唯一候选只有一次领取、attempt1、running 事件1条；100 个饱和任务的事件数量不增（没有声称事件内容逐字段相等）。
- 真实锁等待、并发上限2、跨 pool/owner、NULL lease、确定排序、权限/确认/材料拒绝、候选超时/错误、commit 失败均有专项证据。原 execution snapshot 专项 23 项通过。
- 1001 条 queued 的隔离样本，实际候选 SQL EXPLAIN ANALYZE execution 0.298ms；这是样本，不能推导生产恒定耗时。
- Standards/Spec 最终双轴复审均无阻断。候选离线构建通过，临时上传脚本和精确归属测试资源已清理。
- 未运行真实核销、恢复或调查，未改业务工作簿、历史 marker，未提交或推送。

## 运行生效

镜像 `sha256:85bb307cf1b4625dc5e38692f8878d59217733905eba1d67ae854e550ef54ba0`，API、worker-standard、worker-task-discovery 均一致。

`backend/app/worker.py` 源码及三服务运行 SHA-256：`cac2ff5266139f5f4a1f3bc667bf42dd37e9906abebd61d563bb6f4ac3387cf8`。测试 SHA-256：`27f324604f8c54d1f6580ef26f525379a65431180f03c55e3a64f478b362f345`。

回滚目录 `/home/lee/financial-platform-isolated/releases/managed-20261008-010033-a1c04ea3`。正常维护切换及任务排空完成，API healthy；两个 Worker running，没有 Docker Health 字段。独立回读五项活动计数为0，normal 模式。scheduler、F1 三文件源码/运行 hash 匹配且未改，前端 cfd960 镜像及独立 AR balance.37 保留。

三条历史封存 marker 原样保留，一条仍需调查。浏览器实际检查任务中心（376条列表）、工具中心、核销创建页和历史日期任务：页面正常，导航控制台错误0，完整停止证明不足的警示仍显示，恢复/解锁按钮数量0。未创建或执行新财务任务。领取竞争的行为证据来自隔离 PostgreSQL；浏览器验收仅证明这些页面及 F1 提示没有回归。

## 下一阶段

F2 完成；继续 F4.A：在原 execution 查询及页面中展示有界、脱敏的各次 attempt 元数据。它不等于进程停止证明，不改变占用和恢复权限。完整 F4、F5、F3、A25、G4、CW09、CW10、CW11 仍需后续实现与独立验收。
