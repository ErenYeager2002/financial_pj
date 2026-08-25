# 01 Skill 源码绑定与首次发现

Status: completed

Blocked by: none

## 交付

- 增加 Skill 源码绑定数据模型和数据库迁移。
- 增加 Gitee 仓库首次名称发现、候选读取和管理员确认接口。
- 名称只用于候选发现，确认后保存正式仓库和目录。
- 支持 `candidate`、`bound`、`broken`、`excluded` 状态。

## 验收

- 唯一同名目录可以形成候选并确认。
- 重名、名称不一致、路径越界和重复绑定被拒绝。
- 员工不能读取或修改源码绑定。
- 审计记录不包含凭据和源码正文。

## Comments

- 2026-08-20：已增加绑定模型、Alembic 迁移、Gitee 首次发现、管理员确认与只读列表接口。
- 真实 Gitee `main` 成功解析 commit `7f4f2d8622a3c50a8159c1ff4fc1c3a9e818be16` 和 18 个 Skill。
- 新增 5 项行为测试；连同发布和迁移回归共 19 项通过，相关 Ruff 检查通过。
