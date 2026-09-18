# 改造实施决策记录

## D00：以独立远程 worktree 保存改造

基线为 2cd58e9。保持当前发布源码和运行服务不变，改造分支位于远程持久化 refactor-worktrees/full-platform-20260918。后续上线仍按项目持续授权及方案门禁处理。

## D01：失败基线显式保存

收集错误保留为失败；continue-on-collection-errors 仅用于收集其余证据。不得通过恢复已移除功能开关、删测试、降低身份和材料校验使旧测试通过。

## D02：既有 ADR 不被静态拆分覆盖

ADR 0003 的 Workflow/Pi 固定执行方式与 0006 的 Native 隔离命令边界仍作为当前约束。PR-13/18 若改变运行模型须明确记录兼容、替代和退役证据；本阶段未作架构决策替换。

## D03：CI 的权限和运行边界

GitHub 当前 workflow、check-run 和 commit status 查询均未发现现有配置。新增配置只申请 contents:read，checkout 不保留凭据；测试容器无外网、不挂生产数据。尚未推送，未宣称远端 CI 通过。
