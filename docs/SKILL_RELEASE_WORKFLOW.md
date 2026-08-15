# Skill 受控发布与回退

本流程只允许管理员导入服务器收件箱中的 ZIP 包。管理页面不上传、编辑或执行任意代码。Skill 源码仍在 `finance-skills` 私有 Git 仓库维护，平台仓库只负责受控同步、结构校验、审核、发布和回退。

## 发布前条件

1. 源码仓库没有未提交改动，目标 Skill 的修改已经提交。
2. 平台同步脚本、Manifest 生成规则及版本号修改已经过代码复核。
3. 使用能够覆盖目标 Skill 的真实测试命令，不能用空命令或仅返回成功的占位命令。
4. 写入型、外部动作型或 RPA Skill 在阶段九验收前继续保持 `disabled`。
5. 发布和回退时，目标 Skill 不得存在活动 Run、Workflow 或 Workflow Action。

## 生成发布包

以下 PowerShell 示例只同步一个 Skill 到隔离暂存目录。把尖括号内容替换为实际值：

```powershell
$SourceRepo = 'D:\BESTEASY\finance-skills'
$StageRoot = Join-Path $env:TEMP 'financial-skill-release-<skill-id>'

.\.venv\Scripts\python.exe scripts\sync_finance_skills.py `
  --source "$SourceRepo\skills" `
  --target $StageRoot `
  --skill-id <skill-id>

.\.venv\Scripts\python.exe scripts\stage_skill_release.py `
  --skill-dir "$StageRoot\<skill-id>" `
  --source-repo $SourceRepo `
  --source-skill "$SourceRepo\skills\<skill-id>" `
  --test-command <测试可执行文件> <测试参数>
```

生成工具会拒绝有未提交改动的源码仓库，执行测试后记录源码 Commit、源码树 SHA-256、测试命令、退出码和耗时，并把包写入 `data/skill-release-inbox`。发布包最大 50 MB；解压后最大 200 MB、最多 2000 个文件。

## 管理员操作

1. 打开 Next.js 的“Skill 目录”。管理员区域只列出服务器收件箱中的包。
2. 选择“导入并校验”。系统检查 ZIP 路径、重复路径、符号链接、大小、Manifest、源码信息、测试证据和执行入口，并保存不可变包及内容哈希。
3. 只在“编辑业务元数据”中修改名称、说明、分类、标签、员工展示、业务进度和结果展示。执行入口、适配器、运行限制、权限与代码不能在网页修改。
4. 复核源码 Commit、包 SHA-256、测试证据和业务元数据，填写审核意见后批准或退回。
5. 发布时输入完整确认文字 `发布 <skill-id> <version>`。系统再次验证包和内容哈希、测试证据及活动任务，并以跨进程锁串行切换目录。
6. 回退时选择历史版本并输入 `回退 <skill-id> <version>`。系统执行相同完整性和活动任务检查；切换失败会恢复原目录。

## 审计与恢复

导入、元数据更新、审核、发布、回退以及管理员读取收件箱和版本列表都会写入脱敏审计。审计只记录 Skill ID、版本、Commit、包哈希和结果，不记录源码内容、凭据或业务文件内容。

数据库与 Skill 目录必须作为同一恢复点管理。正式部署前使用 `scripts\backup_database.ps1` 生成并校验备份；数据库迁移或版本切换失败时，先停止 API 和 Worker，再恢复同一时间点的数据库与目录。不得只恢复数据库或只恢复 Skill 目录。
