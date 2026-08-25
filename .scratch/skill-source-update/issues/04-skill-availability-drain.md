# 04 Skill 可用状态与任务排空

Status: completed

Blocked by: 01

## 交付

- 增加与发布状态分离的 Skill 可用状态。
- 所有任务、草稿、工作流和批量入口使用统一状态检查。
- 实现 `enabled → draining → disabled` 和超时恢复。

## 验收

- `draining` 后不能创建新任务，已有不可变快照可以完成。
- 创建任务与进入 `draining` 不存在并发时间窗口。
- 排空超时恢复 `enabled`，不修改生产目录。

## Comments

- 2026-08-20：已增加独立 Skill 可用状态、Alembic 迁移、管理员状态接口和统一新任务入口检查。
- `draining` 已覆盖直接任务、对话工作流、批次和任务草稿；已有记录的查询与执行路径不受影响。
- `draining → disabled` 必须活动任务为零，状态切换与任务创建共用数据库锁；5 项新测试和 47 项相关回归通过。
