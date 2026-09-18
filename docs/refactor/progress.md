# 改造进度

基线提交：`2cd58e91348ff566250f03b882f22c46425bbe1f`。执行规格见 execution-guide.md。

| 阶段 | 状态 | 证据及缺项 |
| --- | --- | --- |
| PR-00 | 进行中 | 已建立独立 Ubuntu worktree、Python/TypeScript 静态盘点、重复候选报告和隔离校验。后端基线失败已记录；文件保留 PostgreSQL 专项 10 项通过。已采集前端冻结依赖复验完成，typecheck/build/契约通过，格式/lint/4 个用例失败仍保留。调用链语义分类、合成样本、完整 PostgreSQL 门禁和 CI 仍未完成。 |
| PR-01 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-02 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-03 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-04 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-05 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-06 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-07 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-08 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-09 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-10 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-11 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-12 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-13 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-14 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-15 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-16 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-17 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-18 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-19 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-20 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |
| PR-21 | 未开始 | 须满足前置阶段门禁，按 execution-guide.md 完成全部要求。 |

G01–G16 均尚未完成验收。没有改动生产服务或执行真实核销。不得将当前静态报告视为重构完成。

## 当前执行入口

分支：refactor/full-platform-20260918；基线：2cd58e91348ff566250f03b882f22c46425bbe1f；本轮以 GitHub 检查点提交保存，提交号以当前分支 git log 为准。没有活动构建或测试进程。

本轮没有引入运行兼容开关；现有线上兼容开关全量状态尚未核验，不推断为关闭。Native/Pi 旧运行路径仍在，未退役。

下个安全任务：修复 Python/Node 检查器超时后的子进程组清理并增加会生成后代进程的回归；随后补 TS 分类与副本来源映射。执行方式：在无网络、只读源码挂载的测试容器内运行 scripts/refactor/check.py --suite safety，并运行 node --test scripts/refactor/tests/*.test.cjs。修复容器清理后重新运行 scripts/refactor/postgres_baseline.py。

待完成：跨模块执行链、所有部署入口与计划任务核实、Pi 产物链、后端契约与静态基线收集、PR-00 审查缺项；PR-01 尚未开始。

## 2026-09-18 同步检查点

用户要求暂停继续改造并同步最近改动到 GitHub。PR-00 仍未完成，不合并 main，不部署或重启生产服务。最新复验：Python safety 23 项通过，Node 3 项通过；PostgreSQL 10 项测试通过，但测试容器清理检查报 TEST_CONTAINER_CLEANUP_INCOMPLETE，整条命令退出 1。同步前检查未发现带 financial.refactor.synthetic 标签的残留容器。子进程组清理代码和回归已保存；下一步先定位 PostgreSQL 清理检查，再继续既有 PR-00 缺项。完整 CI 尚未验证，不应将此提交视为验收通过。
