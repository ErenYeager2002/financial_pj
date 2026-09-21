# PR-03 普通创建入口接入

2026-09-20，main.new_run 接入 run_submission.submit_run，HTTP 仍返回原 Run 形状。准备中 409 SUBMISSION_IN_PROGRESS 附 request_id，异参 409 IDEMPOTENCY_CONFLICT，令牌状态变化 409 SUBMISSION_NOT_READY，非法 key 422。无 key 的旧客户端使用本次生成的独立标识，不虚称跨请求幂等。

adapter 在每阶段 refresh_active_user 并检查 can_run/can_upload，pin 固定 RegisteredSkill、输入 ID/哈希及模型选择/选项摘要，不保存模型 key。模型配置变化拒绝重新解释。prepare_run 支持显式准备上下文，从而占位后按已固定版本进行模型与暂存复制；新的 Run 不把 reservation key 写回旧 idempotency_key。指纹用旧 pin 的 schema 补齐参数默认值，原文保留。最终使用已固定快照和当前权限/文件校验后同事务 persist/bind。已绑定重放使用当前授权 loader，严格校验 owner/department/skill，绕过最新 registry，不绕过授权。

隔离 SQLite 端到端两条路径均通过：正常与 frozen 恢复后持久化，包含真实 API/Worker/文件下载、同 key 重放原 ID、禁止 replay 查询最新 registry、异参冲突、准备仅调用一次。PostgreSQL 原事务回归 38 项通过。SQLite 嵌套事务触发现有 acquire_claim_lock 的重复 BEGIN IMMEDIATE，修正为已有物理事务时用全局锁行无值变化 UPDATE 取得写锁，未持有物理事务时仍 BEGIN IMMEDIATE；不提交/回滚调用者事务。PostgreSQL 锁分支未改。AST、git diff --check 通过。

这是源码入口接入，不是线上生效。真实 PostgreSQL API 层完整并发、实际权限撤销、prepared 中断跨版本、原来历史 key 的迁移兼容策略仍需补验。retry/draft 仍旧路径，前端意图 key 尚未改。PR-02 镜像仍是已固定旧候选；当前源码含 PR-03 新模块/模型/迁移，不能直接使用旧七文件 Dockerfile 重新构建并宣称完整。兼容恢复、完整构建、部署回读尚未完成。未操作看板或线上业务数据。
