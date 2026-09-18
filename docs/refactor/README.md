# 全项目改造执行记录

唯一规格：execution-guide.md。进度：progress.md。所有阶段以真实证据验收，生成报告不自动代表通过。

- reports/requirement-index.json 索引编号条款和 PR/T/G/I 表格项，默认全部 unverified；正文要求仍需人工逐项审核。已有验收注释时生成器拒绝覆盖。
- source-map.md、execution-paths.md、dependency-map.md 提供静态定位；运行可达性尚需单独证据。
- transaction-boundaries.md 区分 AST 候选与已核实的事务行为。
- baseline-failures.md 保存未通过项，禁止删测试使基线变绿。
- reports/PR-00.md 记录当前范围、检查及缺项。

在远程持久化 worktree 实施；生产切换仍按执行规格和活动任务校验执行。PR-00 工具与测试准备不需要重启生产服务。GitHub API 已核实当前仓库 Actions workflow 数量为 0；新增 CI 前仍需核实其他外部检查来源。
