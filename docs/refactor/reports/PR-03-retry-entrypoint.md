# PR-03 普通重试入口

2026-09-20，main.retry 接入 submit_run，使用独立 run.retry operation，保留 retry:<source Run ID> 的既有含义：一个原任务只对应一次重试提交意图，重复网络请求返回该重试；若新任务再次失败，可针对新任务 ID 发起另一次重试。不把网络重试变成无限新执行。首次仍走现有失败/超时、只读、不修改原上传、版本/输入内容检查。

新增 prepare_retry_submission_request。无 reservation 时读取并校验原任务；已有 reservation 则读取原 pin 保存的请求，避免 registry 新发布或输入保留状态变化使已提交结果无法重放。各路径仍 refresh 当前用户并检查工具权限；实际结果 loader 限制 owner/department/skill。存储 pin 新增明确原请求字段，未保存模型凭据。重试审计仍与业务及绑定共享调用方 commit。旧内部 retry_run convenience 尚未迁移，实际 HTTP 已改。

已有 retry API 测试扩展并通过：新任务 ID 不同于原任务、参数保持、重复返回同一 ID、禁止查询最新 registry/调用 prepare 时仍重放成功、未失败任务不能重试、审计存在；真实合成用户的 can_run 撤销后 replay 返回 403。测试扩展初次缺少 select import，补齐后通过。AST 与 git diff --check 通过。顺带补充固定快照根目录符号链接拒绝，未宣称解决所有恶意磁盘并发场景。

源码已改，线上未部署；草稿、前端、完整 PostgreSQL API 验收和兼容发布仍待完成。未执行真实核销、线上回填或看板操作。
