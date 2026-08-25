# 02 固定 Git 源码版本与检查更新

Status: completed

Blocked by: 01

## 交付

- 实现受限 Git 仓库获取和 commit 解析。
- 计算绑定 Skill 目录哈希，与当前发布源码版本比较。
- 提供单 Skill 检查更新接口和幂等结果。

## 验收

- 无变化时不生成发布包。
- 目录消失、名称变化、仓库不可访问时不影响生产版本。
- 禁止越界路径、未允许仓库和危险 Git URL。

## Comments

- 2026-08-20：已实现受限 Gitee Git 获取、固定 commit、绑定目录 SHA-256、检查更新接口和跨进程获取锁。
- 真实 Git smoke 固定到 `7f4f2d8622a3c50a8159c1ff4fc1c3a9e818be16`，`ar-hexiao-daily` 目录哈希为 `f750918f0c4174ed23b2cfc32b2ae5de3082cfa2f8a975173e19ac993e9c8b5f`。
- 新增检查幂等、绑定损坏和 Git/发布哈希一致性测试；相关 16 项回归与 Ruff 通过。
