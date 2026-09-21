# PR-03 草稿确认入口接入

2026-09-20，assistant.confirm_draft 接入 draft_submission，使用独立 draft.confirm scope。准备后在 persist_submission 同 savepoint 中调用 consume_prepared_draft，锁定并刷新草稿后再比对原请求、消费、必要时确认 Run。任务/步骤/事件/幂等绑定/草稿状态共享最终调用方 commit。on_persist 失败整体回滚本次业务 savepoint。

prepare_draft_run_request 在返回 consumed 结果前也刷新当前身份并检查 can_create_draft/can_run；关联 Run 必须匹配 owner/department/skill。草稿读取补部门范围。更新与删除草稿使用行锁并刷新状态，防止并发消费后以陈旧 ready 状态继续编辑/删除。旧 confirm_task_draft 内部兼容入口仍保留；实际 HTTP 入口走新编排。

验证：draft-submission 3 项 API 用例通过，包括确认前无任务、重复确认原任务、文件变更/跨用户拒绝、消费后注入故障的整体回滚、prepared 到期后禁止 prepare_run 仍恢复成功、消费草稿撤销 can_run 后 403。真实 PostgreSQL draft-locking 2 项证明编辑/删除受消费行锁阻塞（55P03），消费提交后重新检查并 409 拒绝。原 PostgreSQL 事务回归 38 项通过。全 task-drafts 在新增用例前为 10 passed/1 known baseline failure：assistant status 返回 model 字段而旧测试期待仅 configured，与本轮无关，未宣称全绿。AST、git diff --check 通过。

尚缺完整 PostgreSQL HTTP 并发/故障验收、前端意图 key、旧路径清理及发布回退方案。PR-02/03 未部署，未回填线上历史，未执行财务任务，看板无改动。
