# 财务 Skill 平台 P3 部署验收记录

日期：2026-08-15

范围：P3-01 至 P3-05。未执行真实财务写入，未记录账号、会话、密钥、任务原文或文件路径。

## 构建与静态检查

- 后端全量 pytest：通过；退出码 0。Windows 结束清理阶段有既有临时目录权限提示，不影响测试结果。
- 本轮后端文件 Ruff：通过。全仓扫描仍有旧版 Skill 厂商脚本和历史迁移中的既有格式问题，本轮未批量改写。
- 前端 TypeScript：通过。
- 前端导航测试：5 项通过；平台数据层与统一任务向导测试：5 项通过。
- 前端 lint：退出码 0；保留 5 个原模板的嵌套组件警告，本轮文件没有新增警告。
- 本机与 Docker 中的 Next.js 生产构建：通过；保留 Google Sans Flex fallback 和 metadataBase 提示。

## 数据库与运行时

- PostgreSQL Alembic revision：`c5d9f3a8201b`。
- PostgreSQL 原生步骤完整性检查：通过。
- 并发领取探针：6 个领取者，1 个进入 running，5 个保持 queued。
- 只读合成试运行：状态 succeeded，输出文件 1 个；3 条银行记录与 3 条台账记录中匹配 2 条。
- 角色冒烟：管理员可读取部门聚合；员工管理员权限检查返回拒绝。
- 模型 Trace 聚合冒烟：在回滚事务内写入 1 次草稿生成前失败调用，聚合结果为失败 1 次、12 ms、输入/输出 Token 5/2；无父级记录可用于保存草稿生成前的失败事实，同时绑定两个父级仍被拒绝，Run/草稿的 owner 与 department 复合外键保持有效。事务回滚后未留下合成记录。

## 部署状态

- API、PostgreSQL、出站服务：healthy。
- Next.js、网关、2 个 Python Worker、2 个 HTTP Worker、2 个 Workflow Worker：running。
- 唯一宿主机入口：`127.0.0.1:8443`。
- `https://localhost:8443/auth/sign-in`：HTTP 200。
- 出站配置检查：有效，当前精确允许目标数量为 1。

## 发布边界

- AI 只生成任务草稿并进入统一任务向导，不能直接改变 Run 或 StepRun。
- 工作流拓扑现阶段只读；未开放自由代码、Shell、数据库写入或 unrestricted HTTP 节点。
- 真实财务写入仍须走已有审批、快照、文件哈希和写后验证流程。
