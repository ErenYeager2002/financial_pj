# 03 单 Skill 发布包

Status: completed

Blocked by: 02

## 交付

- 将源码转换脚本改为只处理指定 Skill。
- 从源码绑定写入上游仓库、目录和 commit，移除硬编码 GitHub 地址。
- 生成不可变发布包、测试结果和差异摘要。

## 验收

- 制包只读取绑定目录并只输出一个 Skill。
- `SKILL.md name`、平台 ID 和 `tool.yaml id` 必须一致。
- 同版本不同内容、版本倒退和测试失败不能进入审核。

## Comments

- 2026-08-20：现有转换脚本已支持单 Skill 的绑定仓库、源码目录、commit 和目标版本参数，并校验 `SKILL.md name`。
- 新增固定 revision worktree 和 `prepare-release` 管理接口；制包后直接进入现有 `validated` 发布记录，不触发生产切换。
- 真实 Gitee worktree smoke、单 Skill 转换、制包、导入及现有发布回归共 20 项通过，相关 Ruff 通过。
