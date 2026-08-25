# Gitee Skill 源码绑定与单 Skill 受控更新规格

状态：实施中

日期：2026-08-20

## 目标

将平台 Skill 与 `https://gitee.com/Lee157/finance-skills.git` 中的源码目录建立可审计绑定。首次按 `SKILL.md` 的 `name` 与平台 `skill_id` 发现候选，经管理员确认后保存仓库、跟踪引用和源码目录；后续只按绑定检查和更新指定 Skill。

更新源码、生成发布包和运行测试期间继续使用旧版本。审核通过后，平台停止接收该 Skill 的新任务，等待已有任务完成，再原子安装、验证并重新启用；失败时恢复原版本。

## 领域规则

1. 名称只用于首次发现候选，正式绑定不能依赖后续名称搜索。
2. 一个平台 Skill 最多有一个有效源码绑定；一个仓库目录最多绑定一个平台 Skill。
3. `skill_id`、源码 `SKILL.md` 的 `name` 和生成后 `tool.yaml` 的 `id` 必须一致。
4. 正式源码位置由仓库地址、跟踪引用和仓库内相对目录组成。每次检查必须解析为不可变 commit，并记录目录内容哈希。
5. 生产版本由 commit、源码目录哈希和发布包哈希共同标识，不能直接执行浮动 `main`。
6. 更新一个 Skill 只能生成和安装该 Skill 的发布包；同一仓库的其他目录不能被连带覆盖。
7. 拉取、比较、测试和审核不改变 Skill 可用状态。生产切换前进入 `draining`，活动任务清零后进入 `disabled`。
8. 安装或验证失败必须恢复原目录。恢复验证失败时保持禁用，不能启用不确定版本。
9. Git 获取、哈希、校验、状态迁移、安装和恢复由确定性代码执行。AI Agent 只能总结差异和辅助审核。
10. 仓库凭据不得进入 URL、日志、审计详情或发布包。当前公开 Gitee 仓库不保存凭据。

## 初始绑定范围

- 为平台与 Gitee 同名的 16 个 Skill 生成候选，不直接自动确认。
- `update-finance-skills` 标记为平台排除项。
- `qige-invoice-to-kingdee` 在平台接入完成后再绑定。
- `jdy-cashflow-export`、`jdy-cashflow-reconcile`、`reconcile-bank` 保持未绑定。

## 模块与接口

### GitSkillSource

- `discover(repository_url, tracking_ref)`：读取仓库 Skill 元数据并返回候选。
- `resolve(binding)`：将跟踪引用解析为 commit 和源码目录哈希。
- `materialize(revision, destination)`：在隔离目录生成固定源码版本。

### SkillUpdate

- `confirm_binding(skill_id, candidate)`：确认并持久化源码绑定。
- `check_update(skill_id)`：比较远端源码版本与当前发布版本。
- `prepare_release(skill_id, revision)`：只为指定 Skill 生成不可变发布包。
- `start_rollout(release_id)`：执行排空、禁用、安装、验证、恢复和启用。

页面、命令行和测试均调用以上模块，不分别实现目录复制和发布状态迁移。

## 用户流程

1. 管理员打开 Skill 来源管理，执行首次发现。
2. 页面展示平台 Skill、Gitee 候选目录、名称和仓库地址；冲突项不能确认。
3. 管理员确认绑定。
4. 后续在单个 Skill 上点击“检查更新”。
5. 有变化时生成发布包和差异摘要，无变化时结束且不产生发布记录。
6. 管理员审核发布包并输入确认文字。
7. 平台执行 `draining → disabled → published → enabled`。

## 安全约束

- 只允许配置的 Git 主机和仓库；禁止本地路径、`file://`、SSH 命令选项和任意 URL 跳转。
- 获取源码时不执行 Git hooks、仓库安装脚本或业务入口。
- 源码路径必须位于绑定目录；发布包拒绝绝对路径、父目录跳转和越界符号链接。
- 每个 Skill 同时最多一个检查、制包或发布任务。
- 审计只记录仓库、目录、commit、哈希、状态和操作人，不记录源码正文或凭据。

## 验收

- 首次发现能为 16 个同名 Skill 生成唯一候选，排除项和平台独有项不会误绑定。
- 重名、名称不一致、目录消失和越界路径均不能确认或更新。
- 后续检查直接使用正式绑定；远端无变化时幂等返回。
- 更新一个 Skill 不改变其他 Skill 的文件、版本、发布记录和可用状态。
- 发布前禁止新任务但允许已有快照完成；等待超时恢复旧版本可用状态。
- 安装、Registry 刷新或健康检查失败时恢复原版本；恢复失败保持禁用。
- 数据库当前发布 commit、源码哈希和运行目录哈希一致。
- 后端测试、迁移测试、前端测试、类型检查、生产构建和运行时健康检查通过。

## 非目标

- 不让平台自动发布 Gitee `main` 的全部变化。
- 不由 AI Agent 直接安装或启用 Skill。
- 不在本功能中把 `update-finance-skills` 发布为员工业务 Skill。
