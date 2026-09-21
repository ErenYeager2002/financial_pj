# 当前事务提交者（PR-02 已上线）

下表是已核对的当前调用链；其后保留历史候选表和实施记录，不以旧行号或旧提交行为代表当前源码。全仓可重复扫描命令：`python3 -B scripts/refactor/transaction_inventory.py`。结果包含每个源文件 SHA-256、直接调用点、类别及分类依据；动态别名、SQL 字符串和非 Python 持久化不在 AST 证明范围内。

| 路径 | 唯一提交者 | 参与同事务的事实 |
| --- | --- | --- |
| 普通任务创建 | main.new_run | Run、步骤、文件绑定、模型追踪、初始事件 |
| 普通任务确认 | main.confirm | 确认字段、排队步骤、状态事件 |
| 普通任务取消 | main.cancel | 取消请求或取消终态、步骤、事件 |
| 普通任务重试 | main.retry | 新任务及 run.retry 审计 |
| 草稿确认消费 | routers.assistant.confirm_draft | 新任务、必要确认、consumed/run_id、draft.confirm 审计 |
| 草稿过期读取 | routers.assistant.get_draft | 过期状态；辅助函数只 flush |
| 草稿创建/更新/删除 | 对应 assistant 路由 | 草稿变更及审计；模型调用事实另见下一行 |
| 模型调用独立事实 | draft_service._persist_model_trace | 自有 Session 内模型事实；后续父草稿关联由调用方提交 |
| Worker 领取 | worker.claim_next_run | 租约、attempt、领取事件、执行步骤 |
| Worker 完成/失败/超时/取消 | worker._execute_claimed_run 对应分支 | 校验后的结果、文件登记、步骤、终态事件及失败审计 |
| 长任务进度 | events.publish_run_progress | 独立 Session 和原 fence 下的进度字段/事件；不能持有父事务的任务写锁 |
| 普通任务心跳 | leases.LeaseHeartbeat._touch | 独立 Session 条件更新租约 |
| 暂存清理心跳 | ar_staging_retention.maintain_staging.heartbeat | 使用调用方 Session 的阶段检查点，非独立心跳 |

旧 emit_event 业务调用剩余 3 处：native_skill_service.execute_command 两处、reap_abandoned_runs 一处。兼容 wrapper 保留，不对 Native 命令路径做全仓替换；Native 幂等/生命周期改造按后续阶段处理。

分类状态：所有直接调用均有类别，但 helper-implicit-commit 类表示服务内部提交、需结合调用方检查，不表示错误已确认或已经修复。管理权限 replace_user_permissions 依方案单列；全平台其他领域的事务改造不得据此自动扩大 PR-02 范围。PR-02 已随 PR-03 后端部署，验收汇总见 reports/PR-02.md。

---

# Transaction boundary candidates

Baseline `2cd58e91348ff566250f03b882f22c46425bbe1f`. Static AST evidence only; dynamic dispatch, imported aliases and runtime reachability require targeted verification.

This lists commit/rollback/flush expressions, not confirmed transaction ownership. Test doubles and unrelated methods can share these names. Classify API use cases, worker claims, checkpoints, heartbeat and implicit helpers before PR-02; no automatic rewrite is justified by this list.

| File | Line | Caller scope | Expression | Classification |
|---|---|---|---|---|
| backend/app/adapters.py | 358 | SubprocessAdapter.register_artifacts | ctx.db.commit | unclassified; verify use-case commit owner |
| backend/app/admin_user_service.py | 96 | list_department_users | db.commit | unclassified; verify use-case commit owner |
| backend/app/admin_user_service.py | 126 | create_department_user | db.commit | unclassified; verify use-case commit owner |
| backend/app/admin_user_service.py | 128 | create_department_user | db.rollback | unclassified; verify use-case commit owner |
| backend/app/admin_user_service.py | 179 | update_department_user | db.commit | unclassified; verify use-case commit owner |
| backend/app/admin_user_service.py | 181 | update_department_user | db.rollback | unclassified; verify use-case commit owner |
| backend/app/admin_user_service.py | 233 | delete_department_user | db.commit | unclassified; verify use-case commit owner |
| backend/app/admin_user_service.py | 257 | reset_department_user_password | db.commit | unclassified; verify use-case commit owner |
| backend/app/approval_service.py | 312 | request_workflow_approval | db.flush | unclassified; verify use-case commit owner |
| backend/app/approval_service.py | 385 | list_approvals | db.commit | unclassified; verify use-case commit owner |
| backend/app/approval_service.py | 448 | decide_approval | db.commit | unclassified; verify use-case commit owner |
| backend/app/approval_service.py | 478 | decide_approval | db.commit | unclassified; verify use-case commit owner |
| backend/app/approval_service.py | 490 | decide_approval | db.commit | unclassified; verify use-case commit owner |
| backend/app/approval_service.py | 555 | decide_approval | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_agent_budget.py | 31 | reserve_agent_call | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_agent_budget.py | 69 | reserve_agent_call | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_agent_budget.py | 74 | reserve_agent_call | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 81 | queue_investigation | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 98 | queue_investigation | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 105 | lock_investigation | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 229 | execute_investigation | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 244 | execute_investigation | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 302 | execute_investigation | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 304 | execute_investigation | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 308 | execute_investigation | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_business_investigation.py | 320 | execute_investigation | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_recovery.py | 154 | recover_execution | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_recovery.py | 219 | recover_execution | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_runner.py | 35 | lock_execution | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_runner.py | 154 | ArExecution.script | self.db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_runner.py | 582 | ArExecution.complete_reconciliation | self.db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_runner.py | 617 | execute_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_runner.py | 643 | queue_execution_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_execution_runner.py | 717 | queue_execution_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_process_evidence.py | 34 | _write_fact | handle.flush | unclassified; verify use-case commit owner |
| backend/app/ar_recovery_adoption.py | 86 | _fence | execution.db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_report_recovery.py | 128 | recover_report | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_staging_archive.py | 103 | build_archive | output.flush | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 35 | _load | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 115 | _save | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 188 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 192 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 204 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 239 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 243 | maintain_staging | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 250 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 267 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 272 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 279 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 308 | maintain_staging.heartbeat | db.commit | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 319 | maintain_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 334 | _failed | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 350 | maintain_expired_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 358 | maintain_expired_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 364 | maintain_expired_staging | db.rollback | unclassified; verify use-case commit owner |
| backend/app/ar_staging_retention.py | 376 | maintain_expired_staging | db.commit | unclassified; verify use-case commit owner |
| backend/app/assistant_chat_service.py | 169 | append_message | db.flush | unclassified; verify use-case commit owner |
| backend/app/assistant_profile_service.py | 87 | configure_assistant_profile | db.flush | unclassified; verify use-case commit owner |
| backend/app/assistant_profile_service.py | 95 | remove_assistant_profile | db.flush | unclassified; verify use-case commit owner |
| backend/app/assistant_title_service.py | 118 | _generate_title | db.commit | unclassified; verify use-case commit owner |
| backend/app/assistant_turn_service.py | 45 | turn_status | db.commit | unclassified; verify use-case commit owner |
| backend/app/assistant_turn_service.py | 61 | mutate_turn | db.commit | unclassified; verify use-case commit owner |
| backend/app/assistant_turn_service.py | 84 | mutate_turn | db.commit | unclassified; verify use-case commit owner |
| backend/app/assistant_workflow_service.py | 159 | prepare | db.commit | unclassified; verify use-case commit owner |
| backend/app/assistant_workflow_service.py | 183 | start | db.commit | unclassified; verify use-case commit owner |
| backend/app/assistant_workflow_service.py | 205 | start | db.rollback | unclassified; verify use-case commit owner |
| backend/app/assistant_workflow_service.py | 212 | start | db.commit | unclassified; verify use-case commit owner |
| backend/app/audit_service.py | 57 | record_audit | db.flush | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 83 | create_user | db.flush | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 120 | get_or_create_development_clerk_admin | db.commit | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 124 | get_or_create_development_clerk_admin | db.rollback | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 158 | login | db.commit | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 162 | login | db.commit | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 176 | create_session | db.flush | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 201 | get_session_user | db.commit | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 211 | revoke_session | db.commit | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 240 | _revoke_sessions | db.commit | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 251 | change_password | db.commit | unclassified; verify use-case commit owner |
| backend/app/auth_service.py | 303 | bootstrap_admin | db.commit | unclassified; verify use-case commit owner |
| backend/app/authorization.py | 105 | replace_user_permissions | db.commit | unclassified; verify use-case commit owner |
| backend/app/avatar_service.py | 72 | save_avatar | db.commit | unclassified; verify use-case commit owner |
| backend/app/avatar_service.py | 77 | save_avatar | db.rollback | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 450 | _get_owned_draft | db.commit | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 496 | prepare_task_draft | db.commit | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 502 | prepare_task_draft | db.commit | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 568 | prepare_task_draft | db.flush | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 605 | update_task_draft | db.flush | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 658 | confirm_task_draft | db.flush | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 673 | delete_task_draft | db.flush | unclassified; verify use-case commit owner |
| backend/app/draft_service.py | 675 | delete_task_draft | db.flush | unclassified; verify use-case commit owner |
| backend/app/events.py | 58 | emit_event | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 381 | materialize_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 382 | materialize_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 403 | materialize_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 425 | materialize_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 426 | materialize_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 434 | materialize_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 435 | materialize_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 440 | materialize_bundle | db.rollback | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 448 | materialize_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 456 | materialize_bundle | db.rollback | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 464 | materialize_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 469 | materialize_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 581 | confirm_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 835 | finalize_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 855 | finalize_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 878 | suspend_bundle_for_retry | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 953 | purge_fetched_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 995 | purge_fetched_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 1014 | purge_fetched_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 1020 | purge_fetched_bundle | db.rollback | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 1031 | purge_fetched_bundle | db.rollback | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 1036 | purge_fetched_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 1039 | purge_fetched_bundle | db.rollback | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 1050 | purge_fetched_bundle | db.rollback | unclassified; verify use-case commit owner |
| backend/app/fetched_bundle_service.py | 1063 | purge_fetched_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/app/fetched_data_preview.py | 286 | _ensure_current_ar_amount_summary | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_data_preview.py | 312 | _build_preview | db.flush | unclassified; verify use-case commit owner |
| backend/app/fetched_data_preview.py | 328 | _build_preview | db.flush | unclassified; verify use-case commit owner |
| backend/app/file_retention.py | 233 | _write_journal | handle.flush | unclassified; verify use-case commit owner |
| backend/app/file_retention.py | 281 | cleanup | db.rollback | unclassified; verify use-case commit owner |
| backend/app/file_retention.py | 286 | cleanup | db.rollback | unclassified; verify use-case commit owner |
| backend/app/file_retention.py | 306 | cleanup | db.commit | unclassified; verify use-case commit owner |
| backend/app/leases.py | 50 | LeaseHeartbeat._touch | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 586 | upload_file | db.rollback | unclassified; verify use-case commit owner |
| backend/app/main.py | 610 | upload_file | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 761 | download_file | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 781 | remove_uploaded_file | db.rollback | unclassified; verify use-case commit owner |
| backend/app/main.py | 792 | remove_uploaded_file | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 929 | get_workflow_batch_fetched_data | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 953 | confirm_workflow_batch_fetched_data | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 988 | supplement_workflow_batch_fetched_data | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 1028 | remove_reusable_workflow_files | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 1089 | restore_workflow_material_set | db.rollback | unclassified; verify use-case commit owner |
| backend/app/main.py | 1092 | restore_workflow_material_set | db.rollback | unclassified; verify use-case commit owner |
| backend/app/main.py | 1106 | restore_workflow_material_set | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 1218 | get_workflow_fetched_data | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 1242 | confirm_workflow_fetched_data | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 1272 | supplement_workflow_fetched_data | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 1386 | rebuild_workflow_result | db.commit | unclassified; verify use-case commit owner |
| backend/app/main.py | 1541 | retry | db.commit | unclassified; verify use-case commit owner |
| backend/app/model_service.py | 304 | _store_connection | db.commit | unclassified; verify use-case commit owner |
| backend/app/model_service.py | 420 | select_model | db.commit | unclassified; verify use-case commit owner |
| backend/app/model_service.py | 450 | refresh_connection | db.commit | unclassified; verify use-case commit owner |
| backend/app/model_service.py | 460 | refresh_connection | db.commit | unclassified; verify use-case commit owner |
| backend/app/model_service.py | 477 | remove_connection | db.commit | unclassified; verify use-case commit owner |
| backend/app/native_skill_service.py | 129 | install_native_skill | db.commit | unclassified; verify use-case commit owner |
| backend/app/native_skill_service.py | 230 | execute_command | db.commit | unclassified; verify use-case commit owner |
| backend/app/native_skill_service.py | 253 | execute_command | db.rollback | unclassified; verify use-case commit owner |
| backend/app/native_skill_service.py | 262 | execute_command | db.commit | unclassified; verify use-case commit owner |
| backend/app/native_skill_service.py | 280 | reap_abandoned_runs | db.commit | unclassified; verify use-case commit owner |
| backend/app/pi_business_query.py | 63 | query | db.commit | unclassified; verify use-case commit owner |
| backend/app/pi_model_access.py | 31 | atomic_json | handle.flush | unclassified; verify use-case commit owner |
| backend/app/pi_model_broker.py | 113 | completions.stream | db.commit | unclassified; verify use-case commit owner |
| backend/app/pi_runtime_service.py | 51 | create_session | stream.flush | unclassified; verify use-case commit owner |
| backend/app/pi_runtime_service.py | 87 | store_mounted_skills | stream.flush | unclassified; verify use-case commit owner |
| backend/app/pi_skill_drafts.py | 61 | propose | db.commit | unclassified; verify use-case commit owner |
| backend/app/pi_skill_drafts.py | 93 | publish | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 145 | append_assistant_conversation_message | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 191 | stream_agent_model | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 197 | stream_agent_model | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 208 | stream_agent_model.body_iterator | trace_db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 262 | prepare_from_agent_recommendation | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 285 | prepare | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 314 | update_draft | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 333 | confirm_draft | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 351 | delete_draft | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 379 | put_admin_profile | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/assistant.py | 396 | delete_admin_profile | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/audit.py | 87 | list_audit_events | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/audit.py | 133 | list_audit_event_page | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/auth.py | 64 | auth_login | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/auth.py | 78 | auth_login | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/auth.py | 115 | auth_change_password | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/auth.py | 130 | auth_logout | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 420 | claim_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 427 | claim_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 433 | claim_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 462 | claim_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 472 | claim_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 482 | claim_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 504 | heartbeat_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 566 | finish_pi_harness_work | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 588 | request_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 600 | request_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 621 | request_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 644 | request_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 667 | request_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 683 | request_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 710 | read_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 741 | stream_pi_harness_model | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 768 | stream_pi_harness_model | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 774 | stream_pi_harness_model | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_harness.py | 785 | stream_pi_harness_model.body_iterator | trace_db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_runtime.py | 41 | create_session | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_runtime.py | 67 | operate | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_runtime.py | 70 | operate | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_runtime.py | 95 | files | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/pi_runtime.py | 117 | download | db.commit | unclassified; verify use-case commit owner |
| backend/app/routers/profile.py | 45 | upload_avatar | db.commit | unclassified; verify use-case commit owner |
| backend/app/run_service.py | 377 | create_run | db.flush | unclassified; verify use-case commit owner |
| backend/app/service_credential_service.py | 95 | save_service_credential | db.commit | unclassified; verify use-case commit owner |
| backend/app/service_credential_service.py | 108 | remove_service_credential | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_availability_service.py | 303 | transition_availability | db.flush | unclassified; verify use-case commit owner |
| backend/app/skill_availability_service.py | 340 | transition_availability | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_availability_service.py | 352 | disable_after_drain | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_dedication_service.py | 86 | list_skill_dedications | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_dedication_service.py | 122 | set_skill_dedication | db.flush | unclassified; verify use-case commit owner |
| backend/app/skill_dedication_service.py | 135 | set_skill_dedication | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_dedication_service.py | 137 | set_skill_dedication | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_dedication_service.py | 164 | clear_skill_dedication | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 154 | _publish_guard | handle.flush | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 269 | list_inbox_packages | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 288 | list_releases | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 455 | import_release | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 460 | import_release | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 464 | import_release | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 500 | update_release_metadata | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 537 | review_release | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 631 | _capture_current_release | db.flush | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 723 | _activate_release | db.flush | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 726 | _activate_release | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 730 | _activate_release | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 776 | publish_release | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_release_service.py | 792 | publish_release | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 101 | start_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 103 | start_rollout | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 133 | _claim_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 152 | _claim_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 156 | _claim_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 192 | _finish_interrupted_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 205 | _finish_interrupted_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 239 | _set_failed_disabled | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 250 | _execute_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 259 | _execute_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 264 | _execute_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 269 | _execute_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 280 | _execute_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 300 | _execute_rollout | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 304 | _handle_rollout_failure | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_rollout_service.py | 325 | _handle_rollout_failure | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_source_service.py | 152 | _source_guard | handle.flush | unclassified; verify use-case commit owner |
| backend/app/skill_source_service.py | 529 | confirm_binding | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_source_service.py | 569 | confirm_binding | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_source_service.py | 571 | confirm_binding | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_source_service.py | 599 | check_update | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_source_service.py | 622 | check_update | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_update_service.py | 205 | update_bound_skill | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_update_service.py | 220 | update_bound_skill | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_update_service.py | 223 | update_bound_skill | db.rollback | unclassified; verify use-case commit owner |
| backend/app/skill_update_service.py | 234 | update_bound_skill | db.commit | unclassified; verify use-case commit owner |
| backend/app/skill_update_service.py | 236 | update_bound_skill | db.rollback | unclassified; verify use-case commit owner |
| backend/app/step_runtime_service.py | 113 | _definition | db.flush | unclassified; verify use-case commit owner |
| backend/app/step_runtime_service.py | 179 | initialize_run_steps | db.flush | unclassified; verify use-case commit owner |
| backend/app/step_runtime_service.py | 210 | queue_run_execution_step | db.flush | unclassified; verify use-case commit owner |
| backend/app/step_runtime_service.py | 223 | start_run_execution_step | db.flush | unclassified; verify use-case commit owner |
| backend/app/step_runtime_service.py | 261 | finish_run_execution_step | db.flush | unclassified; verify use-case commit owner |
| backend/app/storage.py | 98 | save_upload | db.commit | unclassified; verify use-case commit owner |
| backend/app/storage.py | 135 | register_output | db.flush | unclassified; verify use-case commit owner |
| backend/app/storage.py | 389 | delete_upload | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_discovery.py | 207 | execute_task_discovery | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_discovery.py | 246 | execute_task_discovery | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_discovery.py | 250 | execute_task_discovery | db.rollback | unclassified; verify use-case commit owner |
| backend/app/task_discovery.py | 275 | execute_task_discovery | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_discovery_worker.py | 189 | run_discovery_tick | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_reminder_service.py | 129 | save_subscription_owner_credential | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_reminder_service.py | 149 | remove_subscription_owner_credential | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_reminder_service.py | 246 | save_subscription | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_reminder_service.py | 328 | enqueue_task_discovery | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_reminder_service.py | 367 | retry_task_discovery | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_reminder_service.py | 390 | get_task_reminder_board | db.commit | unclassified; verify use-case commit owner |
| backend/app/task_reminder_service.py | 503 | dismiss_resolved_task_reminders | db.commit | unclassified; verify use-case commit owner |
| backend/app/worker.py | 104 | claim_next_run | db.commit | unclassified; verify use-case commit owner |
| backend/app/worker.py | 117 | claim_next_run | db.commit | unclassified; verify use-case commit owner |
| backend/app/worker.py | 127 | execute_run | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_material_service.py | 337 | create_or_replace_current_set | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_material_service.py | 349 | create_or_replace_current_set | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 581 | _set_progress_step | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 593 | _set_progress_step | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 1819 | confirm_fetched_data_review | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 1850 | confirm_fetched_data_review | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 1927 | request_fetched_data_supplement | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 2454 | _cleanup_terminal_fetched_snapshot | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 2969 | create_workflow | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 2985 | create_workflow | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3099 | start_workflow | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3141 | start_workflow | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3380 | start_workflow_batch | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3420 | start_workflow_batch | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3423 | start_workflow_batch | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3755 | cancel_workflow_batch | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3811 | cancel_workflow_batch | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 3894 | cancel_workflow | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4018 | update_workflow_files | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4063 | reset_workflow | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4199 | rebuild_failed_workflow | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4342 | rebuild_failed_workflow | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4525 | queue_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4653 | queue_pi_harness_tool | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4922 | apply_workflow_agent_action | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4929 | apply_workflow_agent_action | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 4969 | send_workflow_message | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5011 | send_workflow_message | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5015 | send_workflow_message | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5131 | claim_next_workflow_action | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5465 | _register_artifact | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5495 | _discard_registered_artifacts | db.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5635 | _write_publish_manifest | handle.flush | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5879 | _execute_named_workflow_phase.persist_workspace_state | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 5912 | _execute_named_workflow_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 6045 | _execute_named_workflow_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 6056 | _execute_named_workflow_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 6099 | _execute_named_workflow_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 6120 | _execute_named_workflow_phase | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 6835 | _reject_superseded_batch_material | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7005 | _finalize_batch_reports | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7061 | _finalize_batch_reports | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7285 | retry_workflow_batch | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7391 | retry_workflow_batch | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7402 | _transition_legacy_fetch_result | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7525 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7530 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7606 | execute_workflow_action | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7678 | execute_workflow_action | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7765 | execute_workflow_action | db.commit | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7977 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7985 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 7990 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 8090 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 8095 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 8099 | execute_workflow_action | db.rollback | unclassified; verify use-case commit owner |
| backend/app/workflow_service.py | 8195 | run_workflow_action_once | db.commit | unclassified; verify use-case commit owner |
| backend/tests/helpers.py | 43 | auth_client | db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 18 | Controls.setUp | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 23 | Controls.test_default_deny_and_separate_namespace | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 25 | Controls.test_default_deny_and_separate_namespace | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 27 | Controls.test_default_deny_and_separate_namespace | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 31 | Controls.test_revocation_reloads_cached_permission | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 33 | Controls.test_revocation_reloads_cached_permission | second.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 36 | Controls.test_disabled_admin_rechecked | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 48 | Controls.test_partial_reply_recovered_on_expiry | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_assistant_controls.py | 66 | Controls.test_actual_failed_run_overrides_claimed_success | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_run_fencing.py | 13 | FenceTests.setUp | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_run_fencing.py | 19 | FenceTests.test_old_attempt_cannot_publish_terminal | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/standalone_run_fencing.py | 20 | FenceTests.test_old_attempt_cannot_publish_terminal | self.db.rollback | unclassified; verify use-case commit owner |
| backend/tests/standalone_run_fencing.py | 25 | FenceTests.test_old_attempt_cannot_publish_file | self.db.flush | unclassified; verify use-case commit owner |
| backend/tests/standalone_run_fencing.py | 30 | FenceTests.test_current_attempt_can_commit | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_admin_workflow_definitions.py | 44 | test_admin_reads_only_department_workflow_topology_without_node_config | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_admin_workflow_definitions.py | 74 | test_admin_reads_only_department_workflow_topology_without_node_config | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_agent_model_gateway.py | 137 | test_agent_skill_directory_uses_draft_permission_not_run_permission | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_agent_model_gateway.py | 190 | test_agent_model_endpoint_streams_and_records_only_safe_metrics | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_approvals.py | 118 | _ready_workflow | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_approvals.py | 127 | _request | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_approvals.py | 149 | test_multiyear_workflow_approval_uses_ledger_years_context | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_approvals.py | 313 | test_expired_approval_cannot_be_decided | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_approvals.py | 351 | test_worker_claims_write_action_without_approval | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_approvals.py | 361 | test_worker_claims_write_action_without_approval | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_ar_allocation_evidence.py | 28 | invoke | ledger.commit | unclassified; verify use-case commit owner |
| backend/tests/test_ar_execution_boundaries.py | 29 | test_context_orders_reloaded_and_new_actions_by_actual_time | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_ar_execution_boundaries.py | 35 | test_context_orders_reloaded_and_new_actions_by_actual_time | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_ar_execution_boundaries.py | 37 | test_context_orders_reloaded_and_new_actions_by_actual_time | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_ar_execution_boundaries.py | 46 | test_v2_action_heartbeat_preserves_queue_isolation | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_ar_execution_boundaries.py | 56 | test_v2_action_heartbeat_preserves_queue_isolation | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_ar_material_candidates.py | 31 | test_candidates_preserve_defaults_scope_roles_and_distinct_same_year_files.add | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_ar_material_candidates.py | 99 | test_hide_referenced_current_files_and_bulk_candidates_without_deleting.add | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_ar_material_candidates.py | 109 | test_hide_referenced_current_files_and_bulk_candidates_without_deleting | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_ar_material_candidates.py | 112 | test_hide_referenced_current_files_and_bulk_candidates_without_deleting | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_ar_material_candidates.py | 118 | test_hide_referenced_current_files_and_bulk_candidates_without_deleting | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_titles.py | 26 | TitleTests.setUp | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_workflows.py | 20 | AssistantWorkflowTests.setUp | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_workflows.py | 31 | AssistantWorkflowTests.setUp.execute | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_workflows.py | 115 | AssistantWorkflowTests.test_denial_consultation_and_quoted_execution_do_not_start | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_workflows.py | 124 | AssistantWorkflowTests.test_rerun_requires_explicit_rerun_context | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_workflows.py | 138 | AssistantWorkflowTests.test_lost_response_returns_atomically_recorded_task | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_workflows.py | 145 | AssistantWorkflowTests.test_continuation_is_bound_to_prepared_date_and_skill | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_assistant_workflows.py | 159 | AssistantWorkflowTests.test_authorization_survives_missing_materials | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_audit.py | 100 | test_audit_cursor_stays_stable_when_reads_create_new_audit_events | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_audit.py | 141 | test_audit_details_redact_sensitive_keys | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_auth.py | 93 | test_disabled_user_session_is_invalidated | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_auth.py | 136 | test_server_runtime_can_forward_local_session_as_prefixed_bearer | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_auth.py | 174 | test_change_password_lifecycle | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_auth.py | 233 | test_change_password_rejects_wrong_current | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_auth.py | 264 | test_employee_password_change_keeps_bootstrap_secret | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_authorization.py | 260 | test_permission_revocation_blocks_waiting_run_confirmation | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_authorization.py | 316 | test_disabling_user_revokes_existing_session | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_authorization.py | 347 | test_admin_password_reset_revokes_sessions_and_records_no_password | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_authorization.py | 419 | test_department_admin_cannot_manage_other_department_users | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_clerk_auth.py | 50 | _mapped_user | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_clerk_auth.py | 330 | test_clerk_mode_disables_local_password_reset | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_feature_controls.py | 17 | _clear_task_discovery_override | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_models.py | 61 | test_fetched_bundle_model_enforces_replay_and_member_uniqueness | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_models.py | 73 | test_fetched_bundle_model_enforces_replay_and_member_uniqueness | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_models.py | 89 | test_fetched_bundle_model_enforces_replay_and_member_uniqueness | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_models.py | 90 | test_fetched_bundle_model_enforces_replay_and_member_uniqueness | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_models.py | 95 | test_fetched_bundle_model_enforces_replay_and_member_uniqueness | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_models.py | 105 | test_fetched_bundle_model_enforces_replay_and_member_uniqueness | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_models.py | 106 | test_fetched_bundle_model_enforces_replay_and_member_uniqueness | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 132 | test_materialize_bundle_atomically_publishes_validated_members | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 140 | test_materialize_bundle_atomically_publishes_validated_members | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 173 | test_materialized_bundle_survives_a_later_caller_rollback | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 181 | test_materialized_bundle_survives_a_later_caller_rollback | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 273 | test_failed_export_temp_cleanup_is_retried_by_bundle_purge | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 376 | test_failed_workflow_invalidates_and_purges_its_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 380 | test_failed_workflow_invalidates_and_purges_its_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 418 | test_retryable_preview_failure_preserves_reviewable_bundle_for_retry | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 422 | test_retryable_preview_failure_preserves_reviewable_bundle_for_retry | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 504 | test_stale_creating_bundle_is_recovered_by_cleanup | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 525 | test_stale_creating_bundle_is_recovered_by_cleanup | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 578 | test_materialize_bundle_persists_bundle_before_linking_workflow_with_foreign_keys | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 586 | test_materialize_bundle_persists_bundle_before_linking_workflow_with_foreign_keys | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 606 | test_materialize_bundle_rejects_unknown_files_without_publishing | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 615 | test_materialize_bundle_rejects_unknown_files_without_publishing | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 639 | test_snapshot_replay_revalidates_hashes_and_stays_with_original_owner | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 657 | test_snapshot_replay_revalidates_hashes_and_stays_with_original_owner | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 668 | test_snapshot_replay_revalidates_hashes_and_stays_with_original_owner | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 691 | test_snapshot_replay_revalidates_hashes_and_stays_with_original_owner | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 716 | test_manifest_requires_every_dataset_once_per_date | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 739 | test_materialize_bundle_rejects_unsafe_member_paths | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 760 | test_materialize_bundle_rejects_declared_but_missing_file | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 787 | test_materialize_bundle_rejects_symlink_members | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 809 | test_repeated_materialization_is_idempotent_only_for_identical_files | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 816 | test_repeated_materialization_is_idempotent_only_for_identical_files | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 851 | test_database_failure_removes_published_directory | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 864 | test_database_failure_removes_published_directory | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 881 | test_confirm_and_finalize_are_owner_scoped_and_idempotent | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 927 | test_preview_mirror_must_match_the_published_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 973 | test_stage_bundle_files_copies_only_the_requested_date_atomically | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1037 | test_stage_bundle_preview_files_allows_reviewable_but_unconfirmed_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1083 | test_expired_bundle_purge_is_terminal_and_idempotent | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1099 | test_expired_bundle_purge_is_terminal_and_idempotent | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1133 | test_active_workflow_reference_blocks_expired_bundle_purge | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1148 | test_active_workflow_reference_blocks_expired_bundle_purge | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1174 | test_bundle_purge_failure_is_sanitized_and_retryable | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1189 | test_bundle_purge_failure_is_sanitized_and_retryable | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1230 | test_replay_bundle_resolution_prefers_bundle_id_and_scopes_legacy_id | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1243 | test_replay_bundle_resolution_prefers_bundle_id_and_scopes_legacy_id | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1298 | test_expired_bundle_cannot_be_selected_for_replay | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1309 | test_expired_bundle_cannot_be_selected_for_replay | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1344 | test_replay_adapter_rechecks_retention_at_export | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1360 | test_replay_adapter_rechecks_retention_at_export | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1382 | test_expired_unconfirmed_bundle_is_purged_after_task_finishes | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1391 | test_expired_unconfirmed_bundle_is_purged_after_task_finishes | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1415 | test_purge_pending_lease_blocks_a_second_worker | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1427 | test_purge_pending_lease_blocks_a_second_worker | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1451 | test_expired_purge_worker_cannot_overwrite_newer_attempt | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1460 | test_expired_purge_worker_cannot_overwrite_newer_attempt | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_fetched_bundle_service.py | 1469 | test_expired_purge_worker_cannot_overwrite_newer_attempt.replace_lease | competing_db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_groups.py | 58 | _file | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_file_groups.py | 111 | test_file_groups_use_real_aggregate_counts_and_the_same_group_filter | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_groups.py | 123 | test_file_groups_use_real_aggregate_counts_and_the_same_group_filter | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_groups.py | 202 | test_file_groups_do_not_scan_delete_status | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_groups.py | 252 | test_historical_output_uses_run_skill_for_group_filter_and_serialization | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 43 | FileRetentionTests.run_record | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 59 | FileRetentionTests.file | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 133 | FileRetentionTests.test_unassigned_but_task_linked_input_is_grouped | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 137 | FileRetentionTests.test_malformed_task_json_blocks_scope | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 143 | FileRetentionTests.test_financial_material_fk_is_preserved | self.db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 144 | FileRetentionTests.test_financial_material_fk_is_preserved | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 165 | FileRetentionTests.test_batch_keeps_all_date_outputs | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 168 | FileRetentionTests.test_batch_keeps_all_date_outputs | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention.py | 175 | FileRetentionTests.test_shared_physical_path_is_not_unlinked | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention_guard.py | 49 | RetentionGuardTests.test_late_reference_waits_then_rejects_retired_file | tx.commit | unclassified; verify use-case commit owner |
| backend/tests/test_file_retention_guard.py | 57 | RetentionGuardTests.test_active_reference_writer_defers_cleanup | tx.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 31 | MaterialLockTests.test_running_task_locks_until_finished | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 35 | MaterialLockTests.test_running_task_locks_until_finished | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 40 | MaterialLockTests.test_failed_batch_does_not_lock_paused_children | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 42 | MaterialLockTests.test_failed_batch_does_not_lock_paused_children | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 46 | MaterialLockTests.test_other_owner_is_independent | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 50 | MaterialLockTests.test_failed_task_with_active_investigation_stays_locked | self.db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 51 | MaterialLockTests.test_failed_task_with_active_investigation_stays_locked | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 55 | MaterialLockTests.test_restore_is_rejected_before_changing_materials | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 58 | MaterialLockTests.test_restore_is_rejected_before_changing_materials | self.db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_material_edit_lock.py | 61 | MaterialLockTests.test_initial_material_entry_remains_available | self.db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_model_trace_records.py | 54 | test_model_trace_allows_pre_draft_record_and_enforces_parent_scope | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_model_trace_records.py | 79 | test_model_trace_allows_pre_draft_record_and_enforces_parent_scope | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_model_trace_records.py | 91 | test_model_trace_allows_pre_draft_record_and_enforces_parent_scope | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_model_trace_records.py | 92 | test_model_trace_allows_pre_draft_record_and_enforces_parent_scope | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_model_trace_records.py | 103 | test_model_trace_allows_pre_draft_record_and_enforces_parent_scope | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_observability.py | 60 | test_admin_observability_summary_is_aggregate_only_and_department_scoped | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_observability.py | 107 | test_admin_observability_summary_is_aggregate_only_and_department_scoped | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_observability.py | 129 | test_admin_observability_summary_is_aggregate_only_and_department_scoped | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_observability.py | 172 | test_admin_observability_summary_is_aggregate_only_and_department_scoped | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 36 | _cancel_pending_jobs | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 135 | test_worker_claims_standard_write_run_without_approval_snapshot | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 143 | test_worker_claims_standard_write_run_without_approval_snapshot | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 154 | test_two_workers_execute_tasks_with_real_overlap | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 210 | test_skill_concurrency_limit_blocks_second_worker | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 223 | test_skill_concurrency_limit_blocks_second_worker | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 230 | test_skill_concurrency_limit_blocks_second_worker | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 240 | test_two_claimers_never_receive_the_same_run | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 269 | test_two_claimers_never_receive_the_same_run | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 291 | test_expired_read_only_run_is_reclaimed_but_write_run_is_not | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 307 | test_expired_read_only_run_is_reclaimed_but_write_run_is_not | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 334 | test_workflow_limit_and_different_skills_can_be_claimed | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 351 | test_workflow_limit_and_different_skills_can_be_claimed | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 358 | test_workflow_limit_and_different_skills_can_be_claimed | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 367 | test_workflow_worker_claims_queued_fetched_data_supplement | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_parallel_workers.py | 382 | test_workflow_worker_claims_queued_fetched_data_supplement | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_resource_isolation.py | 69 | test_employee_run_endpoints_and_sse_are_owner_only | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_resource_isolation.py | 120 | test_employee_workflow_and_batch_endpoints_are_owner_only | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_run_approvals.py | 49 | test_run_owner_reads_bounded_approval_timeline_and_other_user_gets_404 | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_approvals.py | 88 | test_run_owner_reads_bounded_approval_timeline_and_other_user_gets_404 | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 45 | test_standard_run_step_projection_tracks_worker_lifecycle | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 70 | test_standard_run_step_projection_tracks_worker_lifecycle | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 105 | test_failed_read_only_execution_step_is_marked_safely_retryable | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 148 | test_standard_runs_reuse_one_workflow_definition | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 171 | test_cancel_and_expired_lease_keep_execution_step_in_sync | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 181 | test_cancel_and_expired_lease_keep_execution_step_in_sync | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 210 | test_run_detail_and_event_stream_redact_worker_error_values | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_step_runtime.py | 223 | test_run_detail_and_event_stream_redact_worker_error_values | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_run_steps.py | 53 | test_run_owner_can_read_sanitized_step_timeline | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_steps.py | 68 | test_run_owner_can_read_sanitized_step_timeline | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_steps.py | 93 | test_run_owner_can_read_sanitized_step_timeline | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_run_steps.py | 186 | test_step_timeline_is_ordered_and_legacy_run_returns_empty_list | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_steps.py | 210 | test_step_timeline_is_ordered_and_legacy_run_returns_empty_list | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_run_steps.py | 229 | test_step_timeline_is_ordered_and_legacy_run_returns_empty_list | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 55 | _file | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 72 | _bind_current_material | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 83 | _bind_current_material | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 101 | test_selectable_input_files_default_page_is_lightweight_and_sorted | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 147 | test_selectable_input_files_are_owner_scoped_and_queryable | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 153 | test_selectable_input_files_are_owner_scoped_and_queryable | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 185 | test_selectable_input_file_ids_keep_only_authorized_current_inputs | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 192 | test_selectable_input_file_ids_keep_only_authorized_current_inputs | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_selectable_input_files.py | 237 | test_selectable_input_file_ids_do_not_scan_delete_status | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_availability.py | 91 | test_draining_cannot_become_disabled_while_active_work_exists | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_availability.py | 102 | test_draining_cannot_become_disabled_while_active_work_exists | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_dedications.py | 40 | _create_user | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_dedications.py | 171 | test_disabled_existing_dedication_is_kept_and_reported | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_dedications.py | 204 | test_setting_dedication_does_not_change_skill_permissions_and_audit_is_minimal | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_direct_update.py | 85 | test_direct_update_pulls_package_replaces_skill_and_enables_it | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_direct_update.py | 97 | test_direct_update_pulls_package_replaces_skill_and_enables_it.fake_check_update | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_direct_update.py | 154 | test_direct_update_pulls_package_replaces_skill_and_enables_it | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_releases.py | 258 | test_release_publish_is_blocked_by_active_run | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_releases.py | 269 | test_release_publish_is_blocked_by_active_run | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_rollouts.py | 66 | isolate_rollouts | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_rollouts.py | 72 | isolate_rollouts | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_rollouts.py | 108 | test_rollout_disables_activates_verifies_and_enables | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_rollouts.py | 154 | test_rollout_waits_for_active_work_then_continues | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_rollouts.py | 167 | test_rollout_waits_for_active_work_then_continues | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_rollouts.py | 246 | test_interrupted_verification_recovers_confirmed_target_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_source_bindings.py | 26 | isolate_source_bindings | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_source_bindings.py | 30 | isolate_source_bindings | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_source_bindings.py | 208 | test_check_update_uses_binding_and_is_idempotent | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_skill_source_bindings.py | 377 | test_prepare_single_bound_skill_creates_validated_release | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_snapshot_replay.py | 139 | test_fetch_history_distinguishes_replayable_bundle_from_purged_preview | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_snapshot_replay.py | 159 | test_fetch_history_distinguishes_replayable_bundle_from_purged_preview | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_snapshot_replay.py | 172 | test_fetch_history_distinguishes_replayable_bundle_from_purged_preview | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_center.py | 142 | _seed_owner_records | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_drafts.py | 77 | _configure_profile | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_drafts.py | 522 | test_assistant_requires_profile_and_rejects_unauthorized_recommendation | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 45 | _create_employee | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 238 | test_discovery_worker_runs_due_check_once | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 362 | test_workflow_success_resolves_only_its_reminder_date | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 366 | test_workflow_success_resolves_only_its_reminder_date | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 422 | test_owner_can_clear_successful_reminders_without_rediscovery | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 425 | test_owner_can_clear_successful_reminders_without_rediscovery | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 567 | test_admin_cannot_dismiss_another_owners_successful_reminder | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 638 | test_failed_and_cancelled_formal_tasks_keep_reminders_pending | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 642 | test_failed_and_cancelled_formal_tasks_keep_reminders_pending | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 725 | test_failed_batch_restores_all_unsuccessful_reminders_to_pending | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 731 | test_failed_batch_restores_all_unsuccessful_reminders_to_pending | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 808 | test_failed_batch_does_not_use_success_older_than_a_reopened_reminder | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 816 | test_failed_batch_does_not_use_success_older_than_a_reopened_reminder | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 937 | test_owner_change_preserves_formal_task_and_reopens_changed_completed_date | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 942 | test_owner_change_preserves_formal_task_and_reopens_changed_completed_date | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 1005 | test_formal_workflow_is_blocked_while_read_only_discovery_is_running | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 1013 | test_formal_workflow_is_blocked_while_read_only_discovery_is_running | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 1064 | test_queued_conversational_workflow_waits_for_running_discovery | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 1073 | test_queued_conversational_workflow_waits_for_running_discovery | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 1118 | test_expired_formal_worker_restores_linked_reminder | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_task_reminders.py | 1121 | test_expired_formal_worker_restores_linked_reminder | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_user_storage_migration.py | 79 | _legacy_data | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workbench_files_runs.py | 53 | _create_failed_run | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workbench_files_runs.py | 106 | test_run_event_history_is_owner_scoped_and_pageable | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workbench_files_runs.py | 243 | test_file_center_latest_view_hides_older_duplicate_outputs | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 224 | _append_material_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 236 | _append_material_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 281 | _finish_all_ar_workflows | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 330 | test_ar_workflow_has_business_id_and_blocks_concurrent_start | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 541 | test_batch_excludes_successful_prefix_on_current_material_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 588 | test_batch_excludes_successful_suffix_on_current_material_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 647 | test_reopened_successful_date_can_start_a_new_batch | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 693 | test_batch_excludes_successful_middle_date_on_current_material_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 752 | test_completed_batch_dates_remain_successful_across_material_lineage | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 934 | test_batch_tracks_its_own_published_material_for_later_retry | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1021 | test_failed_batch_retry_rejects_superseded_material_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1127 | test_failed_range_report_retries_without_rerunning_daily_tasks | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1218 | test_failed_range_report_retries_without_rerunning_daily_tasks | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1321 | test_running_batch_atomic_write_cannot_be_cancelled | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1362 | test_running_batch_cancellation_is_idempotent_and_audited_once | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1435 | test_active_workflow_can_be_cancelled_and_releases_single_flight | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1499 | test_running_fetch_observes_cancellation_before_advancing | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1521 | test_running_fetch_observes_cancellation_before_advancing | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1565 | test_worker_progress_update_preserves_concurrent_cancellation_flag | cancelling_db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1614 | test_input_copy_completion_preserves_concurrent_cancellation_flag.copy_then_cancel | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1630 | test_input_copy_completion_preserves_concurrent_cancellation_flag | worker_db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1675 | test_running_atomic_write_cannot_be_cancelled | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1763 | test_owner_can_cancel_after_skill_permission_is_revoked | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1807 | test_owner_can_cancel_by_message_after_skill_permission_is_revoked | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1852 | test_failed_batch_retry_is_blocked_while_another_ar_task_is_active | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1871 | test_failed_batch_retry_is_blocked_while_another_ar_task_is_active | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1890 | test_failed_batch_retry_is_blocked_while_another_ar_task_is_active | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1912 | test_failed_batch_retry_is_blocked_while_another_ar_task_is_active | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 1978 | test_failed_batch_retry_discards_partial_fetch_snapshot_and_creates_new_attempt | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2076 | test_batch_fetched_data_is_reviewed_once_and_can_preview_each_date | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2172 | test_batch_fetched_data_uses_retried_date_after_primary_snapshot_cleanup | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2241 | test_fetched_data_preview_is_task_scoped_paginated_and_hides_technical_columns | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2360 | test_fetched_data_preview_groups_complete_business_data_by_ar | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2475 | test_fetched_data_preview_groups_complete_business_data_by_ar | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2591 | execute_next_action | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2593 | execute_next_action | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2630 | test_failed_workflow_action_discards_fetched_snapshot.fail_after_fetch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2745 | test_successful_workflow_keeps_fetched_preview_readable_after_cleanup | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 2759 | test_successful_workflow_keeps_fetched_preview_readable_after_cleanup | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 3365 | test_workflow_reuses_and_updates_the_two_material_roles | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 3385 | test_workflow_reuses_and_updates_the_two_material_roles | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 4830 | test_conversational_workflow_hard_gates | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 4953 | test_workflow_reset_clears_current_state_and_preserves_audit | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 4972 | test_workflow_reset_clears_current_state_and_preserves_audit | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 5010 | test_workflow_reset_clears_current_state_and_preserves_audit | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 5030 | test_workflow_reset_clears_current_state_and_preserves_audit | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 5129 | test_multi_date_batch_runs_children_in_order_and_chains_files | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow.py | 5140 | test_multi_date_batch_runs_children_in_order_and_chains_files | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 23 | _workflow | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 63 | test_terminal_snapshot_cleanup_failure_preserves_completed_result | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 68 | test_terminal_snapshot_cleanup_failure_preserves_completed_result | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 132 | test_fetch_pipeline_runs_one_named_action_per_phase | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 235 | test_prepare_workspace_reuses_reviewable_bundle_by_rebuilding_preview | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 260 | test_fetched_data_confirmation_is_idempotent_for_plan_action | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 287 | test_named_fetch_pipeline_cannot_confirm_without_a_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 297 | test_named_fetch_pipeline_cannot_confirm_without_a_bundle | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 369 | test_fetch_action_accepts_current_skill_export_schema_and_publishes_bundle | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 404 | test_action_failure_recovers_failed_transaction_before_recording_error | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 418 | test_action_failure_recovers_failed_transaction_before_recording_error | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_action_pipeline.py | 480 | test_fetch_action_replays_bundle_without_live_fetch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_agent_adapter.py | 225 | test_workflow_agent_action_endpoint_keeps_worker_execution_behind_the_api | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 61 | _file | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 106 | test_legacy_started_workflow_establishes_first_material_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 109 | test_legacy_started_workflow_establishes_first_material_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 141 | test_legacy_started_workflow_binds_matching_current_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 144 | test_legacy_started_workflow_binds_matching_current_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 177 | test_legacy_started_workflow_cannot_replace_different_current_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 222 | test_bound_stale_workflow_is_rejected_before_writing | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 292 | test_upload_set_becomes_current_and_preserves_all_annual_ledgers | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 323 | test_successful_workflow_publishes_successor_used_by_next_task | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 347 | test_successful_workflow_publishes_successor_used_by_next_task | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 381 | test_stale_workflow_cannot_replace_a_newer_current_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 457 | test_material_version_readback_failure_keeps_previous_current | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 546 | test_next_independent_workflow_can_copy_published_output_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 571 | test_next_independent_workflow_can_copy_published_output_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 583 | test_next_independent_workflow_can_copy_published_output_version | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 628 | test_history_lists_current_first_and_restore_creates_a_new_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 636 | test_history_lists_current_first_and_restore_creates_a_new_version | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 662 | test_restore_rejects_material_set_from_another_user | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_material_sets.py | 683 | test_file_in_material_version_cannot_be_deleted | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 86 | _add_standard_step_run | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 99 | _add_standard_step_run | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 113 | _add_standard_step_run | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 122 | _add_standard_step_run | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 178 | test_step_execution_keeps_versioned_file_and_approval_snapshots | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 195 | test_step_execution_keeps_versioned_file_and_approval_snapshots | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 250 | test_step_execution_keeps_versioned_file_and_approval_snapshots | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 252 | test_step_execution_keeps_versioned_file_and_approval_snapshots | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 254 | test_step_execution_keeps_versioned_file_and_approval_snapshots | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 256 | test_step_execution_keeps_versioned_file_and_approval_snapshots | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 261 | test_step_execution_keeps_versioned_file_and_approval_snapshots | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 325 | test_workflow_step_runs_are_scoped_to_their_owner | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 340 | test_workflow_step_runs_are_scoped_to_their_owner | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 354 | test_workflow_step_runs_are_scoped_to_their_owner | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 373 | test_workflow_step_runs_are_scoped_to_their_owner | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 405 | test_step_definition_rejects_uncontrolled_step_type | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 419 | test_step_definition_rejects_uncontrolled_step_type | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 435 | test_step_definition_rejects_uncontrolled_step_type | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 478 | test_step_run_rejects_run_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 492 | test_step_run_rejects_run_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 506 | test_step_run_rejects_run_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 518 | test_step_run_rejects_run_scope_mismatch | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 554 | test_step_run_rejects_step_definition_department_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 568 | test_step_run_rejects_step_definition_department_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 582 | test_step_run_rejects_step_definition_department_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 594 | test_step_run_rejects_step_definition_department_mismatch | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 639 | test_step_run_rejects_workflow_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 653 | test_step_run_rejects_workflow_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 668 | test_step_run_rejects_workflow_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 680 | test_step_run_rejects_workflow_scope_mismatch | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 719 | test_artifact_binding_rejects_parent_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 734 | test_artifact_binding_rejects_parent_scope_mismatch | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 770 | test_approval_binding_rejects_parent_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 787 | test_approval_binding_rejects_parent_scope_mismatch | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 800 | test_approval_binding_rejects_parent_scope_mismatch | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 834 | test_non_idempotent_step_rejects_retry_configuration | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 856 | test_non_idempotent_step_run_cannot_be_marked_retryable | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 860 | test_non_idempotent_step_run_cannot_be_marked_retryable | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 882 | test_workflow_creator_must_belong_to_definition_department | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 898 | test_workflow_creator_must_belong_to_definition_department | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 942 | test_workflow_step_models_reject_uncontrolled_values | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 974 | test_binding_snapshots_are_immutable_after_insert | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1002 | test_binding_snapshots_are_immutable_after_insert | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1012 | test_binding_snapshots_are_immutable_after_insert | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1020 | test_binding_snapshots_are_immutable_after_insert | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1022 | test_binding_snapshots_are_immutable_after_insert | db.rollback | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1027 | test_binding_snapshots_are_immutable_after_insert | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1064 | test_legacy_standard_run_worker_claim_does_not_require_step_rows | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1088 | test_legacy_workflow_worker_claim_does_not_require_step_rows | db.flush | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1112 | test_legacy_workflow_worker_claim_does_not_require_step_rows | db.commit | unclassified; verify use-case commit owner |
| backend/tests/test_workflow_step_models.py | 1159 | test_legacy_run_step_api_returns_empty_timeline | db.commit | unclassified; verify use-case commit owner |
| deployment/deploy_tool.py | 65 | atomic_write | handle.flush | unclassified; verify use-case commit owner |
| deployment/deploy_tool.py | 304 | ToolDeployment.operation | self.control.stdin.flush | unclassified; verify use-case commit owner |
| deployment/native_agent_jobs.py | 78 | AgentJobs._save | stream.flush | unclassified; verify use-case commit owner |
| deployment/pi_runtime_server.py | 262 | PiProcess.send | self.process.stdin.flush | unclassified; verify use-case commit owner |
| deployment/test_tool_runtime_control.py | 20 | RuntimeControlTests.setUpClass | db.flush | unclassified; verify use-case commit owner |
| deployment/test_tool_runtime_control.py | 21 | RuntimeControlTests.setUpClass | db.commit | unclassified; verify use-case commit owner |
| deployment/test_tool_runtime_control.py | 59 | RuntimeControlTests.test_queued_action_blocks_disable_even_if_workflow_is_terminal | db.flush | unclassified; verify use-case commit owner |
| deployment/test_tool_runtime_control.py | 60 | RuntimeControlTests.test_queued_action_blocks_disable_even_if_workflow_is_terminal | db.commit | unclassified; verify use-case commit owner |
| deployment/tool_runtime_control.py | 34 | main | db.rollback | unclassified; verify use-case commit owner |
| deployment/tool_runtime_control.py | 67 | main | db.rollback | unclassified; verify use-case commit owner |
| deployment/tool_runtime_control.py | 105 | main | db.rollback | unclassified; verify use-case commit owner |
| deployment/tool_runtime_control.py | 108 | main | db.rollback | unclassified; verify use-case commit owner |
| deployment/tool_runtime_control.py | 113 | main | db.rollback | unclassified; verify use-case commit owner |
| native-skill-overrides/ar-hexiao-daily/scripts/apply_all.py | 55 | _record_done | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| native-skill-overrides/ar-hexiao-daily/scripts/complete_execution.py | 49 | build | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| native-skill-overrides/ar-hexiao-daily/scripts/verify_execution_write.py | 196 | main | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| scripts/migrate_user_storage.py | 301 | main | db.commit | unclassified; verify use-case commit owner |
| scripts/migrate_user_storage.py | 320 | main | db.rollback | unclassified; verify use-case commit owner |
| scripts/run_stage10_pilot.py | 61 | _input_file | db.flush | unclassified; verify use-case commit owner |
| scripts/run_stage10_pilot.py | 143 | main | db.commit | unclassified; verify use-case commit owner |
| scripts/select_current_workflow_material_set.py | 84 | main | db.commit | unclassified; verify use-case commit owner |
| scripts/select_current_workflow_material_set.py | 87 | main | db.rollback | unclassified; verify use-case commit owner |
| scripts/validate_postgres_runtime.py | 111 | main | db.commit | unclassified; verify use-case commit owner |
| scripts/validate_postgres_runtime.py | 187 | main | db.commit | unclassified; verify use-case commit owner |
| scripts/verify_step_integrity.py | 67 | main | db.flush | unclassified; verify use-case commit owner |
| scripts/verify_step_integrity.py | 81 | main | db.flush | unclassified; verify use-case commit owner |
| scripts/verify_step_integrity.py | 93 | main | db.flush | unclassified; verify use-case commit owner |
| scripts/verify_step_integrity.py | 102 | main | db.flush | unclassified; verify use-case commit owner |
| scripts/verify_step_integrity.py | 114 | main | db.flush | unclassified; verify use-case commit owner |
| scripts/verify_step_integrity.py | 133 | main | transaction.rollback | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily-lab/tests/test_no_num_sequence.py | 169 | SequenceTests.test_write_readback_and_replay | FAL.commit | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily-lab/tests/test_no_num_sequence.py | 179 | SequenceTests.test_write_readback_and_replay | FAL.commit | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily-lab/vendor/scripts/apply_all.py | 55 | _record_done | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily-lab/vendor/scripts/complete_execution.py | 49 | build | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily-lab/vendor/scripts/verify_execution_write.py | 197 | main | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily/vendor/scripts/apply_all.py | 55 | _record_done | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily/vendor/scripts/complete_execution.py | 49 | build | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| skills/ar-hexiao-daily/vendor/scripts/verify_execution_write.py | 197 | main | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/scripts/apply_all.py | 55 | _record_done | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/scripts/complete_execution.py | 49 | build | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/scripts/verify_execution_write.py | 193 | main | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_baseline_receipts.py | 79 | test_existing_blank_receipt_continues_without_changing_original_receivable | F.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_baseline_receipts.py | 237 | test_later_sibling_settlement_backfills_accrual_and_publishes_replay_evidence | F.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_baseline_receipts.py | 249 | test_later_sibling_settlement_backfills_accrual_and_publishes_replay_evidence | F.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_baseline_receipts.py | 331 | test_so_delivery_reaches_existing_group_before_sod_capacity_check | F.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_misjudgment_regressions.py | 413 | test_next_parent_continues_from_first_outstanding_order | FAL.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_misjudgment_regressions.py | 435 | test_same_parent_rerun_reuses_successful_allocation | FAL.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_misjudgment_regressions.py | 459 | test_same_parent_partial_rerun_skips_materialized_split | FAL.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_parent_allocation_history.py | 129 | test_partial_parent_keeps_original_allocation_without_counting_pending_money | FAL.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_parent_allocation_history.py | 151 | test_partial_sod_history_and_waterfall_replay_keep_only_actual_written_amounts | FAL.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_parent_allocation_history.py | 171 | test_partial_sod_history_and_waterfall_replay_keep_only_actual_written_amounts | FAL.commit | unclassified; verify use-case commit owner |
| sources/finance-skills/skills/ar-hexiao-daily/tests/test_parent_allocation_history.py | 182 | test_unwritten_order_without_local_amount_does_not_block_successful_evidence | FAL.commit | unclassified; verify use-case commit owner |
| standalone-skills/ar-hexiao-daily/scripts/apply_all.py | 55 | _record_done | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| standalone-skills/ar-hexiao-daily/scripts/complete_execution.py | 49 | build | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |
| standalone-skills/ar-hexiao-daily/scripts/verify_execution_write.py | 196 | main | fallback_allocation_ledger.commit | unclassified; verify use-case commit owner |

## 已逐段核对的辅助边界

- backend/app/events.py:emit_event：默认 commit=True，状态变化、事件及失败审计使用传入 Session，然后 db.commit()。因此会提交该 Session 其他已挂起修改；PR-02 必须按调用路径迁移，不可只改默认值。
- backend/app/audit_service.py:record_audit：db.add + db.flush，无 commit；事务所有者是调用方。与 emit_event 共用 Session 时由后者默认提交。

其余表格项仍是候选，尚未核实唯一提交者。


## PR-02 当前源码核验（2026-09-18）

更新后的 Python AST 清单见 `reports/PR-02-transaction-call-inventory.json`：537 个直接 commit 表达式、14 个 emit_event 调用，解析错误为零。数字包含测试及可能同名的非数据库方法，不等同于已完成语义分类；动态别名和非 Python 调用尚需另查。以下事实已逐函数检查，旧表行号仅用于历史基线。

| 用例 | 当前行为 | 所需调整 |
| --- | --- | --- |
| create_run | 初始 emit_event 默认提交任务、步骤、模型追踪 | prepare/persist 分离，persist 接受外层事务 |
| confirm_run | emit_event 提交确认字段和步骤 | 外层用例唯一提交 |
| cancel_run | 两条分支都依赖 emit_event 提交 | 外层用例唯一提交 |
| confirm_task_draft | create_run 先提交，必要时 confirm_run 再提交，之后才 flush consumed 和 run_id | 任务与草稿消费必须同事务，排除任务已保存而草稿未消费窗口 |
| record_audit | add/flush，无 commit | 保留追加行为，新 append_run_event 不得提交 |
| _get_owned_draft | 过期时隐式 commit | 检查调用者后移动提交边界 |
| prepare_task_draft | 模型事实先 commit，后续草稿仅 flush | 审查独立事实事务，避免提前提交调用方数据 |

run_fencing 的 before_flush 在未绑定 fence 时返回；绑定时检查 Worker、attempt、状态与租约并加行锁。新 Session 不会自动继承 fence，进度短事务必须重新绑定并核验。

当前仅完成以上诊断与调用清单，尚未修改提交行为。下一步核对路由唯一提交者及文件绑定，再引入兼容事件接口和失败注入测试；不将静态清单视为完整事务审计或上线验收。未执行真实财务任务，未操作看板平台。


### PR-02 事件接口实现进度

已新增 append_run_event，事件及失败审计参与调用方事务，不自行 commit。emit_event 保留原签名和默认提交行为，现有 14 个业务调用尚未迁移。

隔离合成 SQLite 经正式 Alembic 迁移后，event-transactions 套件 8 项通过：三种状态的回滚、整体提交及失败审计脱敏、旧 wrapper 的两种 commit 选项、审计追加后异常回滚、过期 Worker fence 拒绝写入。测试容器无网络、源码只读、测试库位于临时内存目录；没有真实任务或财务写入。静态 git diff --check 通过。

已核实当前普通 new_run/confirm/cancel 路由没有显式 commit；assistant.confirm_draft 路由在追加 draft.confirm 审计后 commit。下一步必须把 prepare/persist、普通路由、retry_run 和草稿消费一起改为清晰的事务所有权，不能仅替换事件调用后上线。本接口尚未部署，PR-02 未完成。


### PR-02 普通提交调用链实施进度

已将 run_service 拆为 prepare_run 与 persist_run，PreparedRun 保存未入库任务及模型解析事实；persist_run 创建任务、五个步骤、模型追踪和初始事件，不 commit。create_run 是组合入口，不再隐式提交；confirm_run/cancel_run 同样改用 append_run_event。main.new_run/confirm/cancel 显式提交；main.retry 原有审计后提交覆盖新任务；assistant.confirm_draft 原有审计后提交覆盖任务、确认和草稿消费。

隔离 event-transactions 17 项通过，新增实际 persist_run 在任务、步骤、事件、审计后的异常回滚，以及实际 confirm_task_draft 的绑定失败注入，覆盖需要确认和无需确认两种任务。绑定失败时任务及关联记录为零，重新读取草稿仍为 ready 且 run_id 为空；成功提交后整体存在。ordinary-e2e 上传、任务创建、确认、Worker 执行、下载通过。git diff --check 通过。

尚未完成：准备阶段长操作事务边界、独立进度事务及 fence 传递、全调用表语义分类、其他入口/别名与过期草稿提交核验、真实 PostgreSQL 专项验证、代码审查与部署。本阶段修改仅存在远程持久化源码，线上仍为 PR-01 版本；不宣称 PR-02 已完成。


### 2026-09-20 恢复实施

运行核对：财务平台三个后端服务仍使用 PR-01 镜像 1a051c67b34d，API healthy；五类活动计数均为零。只检查财务 Compose 项目，未操作看板。

_get_owned_draft 的过期状态改为 flush，GET 路由拥有持久化提交；拒绝确认/更新时由请求会话回滚，不再提交调用方无关数据。模型调用事实通过 _persist_model_trace 的独立 Session 保存，再加入调用方 Session 完成草稿关联；模型失败事实仍可保留，调用方未提交任务不会被连带提交。

event-transactions 19 项通过，包括过期草稿与独立模型事实的新回归。task-drafts 10 项通过、1 项失败：test_assistant_profile_details_are_admin_only 在 assistant/status 多返回 model 字段的旧断言处失败；相关实现、响应模型和测试与 HEAD 相同，本轮没有改动该接口契约。失败保留，不能宣称该套件全通过。git diff --check 通过。仍未部署 PR-02，后续需完成进度短事务、准备阶段边界、调用分类、PostgreSQL 专项和审查。


### Worker 领取与终态事务

claim_next_run 现在只提交一次，领取租约、运行事件与执行步骤同事务。Worker 终态分支显式 commit，全部使用 append_run_event。SubprocessAdapter.register_artifacts 改为 flush，文件登记和报表数据库快照跟随 Worker 校验后的成功终态提交，不再由辅助函数提前提交。

执行异常时 _reload_after_execution_failure 先 rollback，再按固定 run_id 重新读取并以原 fence 验证租约，才追加失败/超时/取消事实。租约丢失不覆盖其他执行者结果；终态提交已成功而响应丢失时，回读终态不再符合运行 fence，因此保留成功结果，不误记为失败。

event-transactions 25 项通过，新增领取步骤失败整体回滚、领取仅一次提交、普通异常/超时/取消撤销未发布结果、成功提交后连接异常保持成功。ordinary-e2e 通过，git diff --check 通过。仍未部署；ExecutionContext.emit 的长操作进度独立事务、准备阶段复制边界和 PostgreSQL 验证仍待完成。看板平台无操作。


### 长操作进度与 PostgreSQL 验证

ExecutionContext.emit 已改为 publish_run_progress：独立 Session、显式传递原 fence、写入前加锁检查执行者/attempt/状态/租约；只允许 running/waiting_user_action 状态，终态仍由 Worker 用例提交。回填调用方 ORM 时只同步实际已提交的进度字段，不刷新或提交未发布结果；若对应字段有调用方待写修改，拒绝覆盖。PostgreSQL 进度行锁等待上限 5 秒，不能为保存进度强行提交父事务。

SQLite event-transactions 28 项通过，ordinary-e2e 通过。相同 28 项通过独立 PostgreSQL 容器验证，每项使用随机独立 schema 和正式迁移。首轮 17 项因合成夹具缺少 workflow_definitions 所需用户外键而失败，补齐合成用户后全部通过；未禁用 PostgreSQL 约束。测试容器无生产网络、无生产数据挂载、无对外端口，按所有权标签清理完毕。新增测试覆盖进度单独提交而主事务结果回滚、缺失和错误 attempt fence 拒绝进度。

未部署；准备阶段长操作、完整调用分类和代码审查仍未完成。独立进度在调用方已经持有同一任务写锁时可能等待并报锁超时，需后续核对所有适配器路径，不能把该情况下的测试缺失当作已验收。


### 快照暂存和中期审查

_snapshot_skill 先复制到唯一 skill.staging-UUID 目录，全部复制成功才重命名为 skill。失败保留可回收孤儿，不发布部分目录；已有正式快照拒绝替换。SQLite 30 项通过；PostgreSQL 31 项通过，包含新快照测试和父事务已经 flush 时进度行锁超时测试，证明不会替父事务提交、回滚或保存未完成结果。该锁冲突边界已经写进接口契约，内置适配器当前均在产物 flush 之前发送进度。

双轴中期审查见 reports/PR-02-review.md：没有规范硬性阻断，但准备阶段事务分离与全仓提交分类仍未完成，阶段不可交付。LlmConfig 类型已补齐。未部署、未操作看板。


### 准备阶段的自有查询会话

prepare_run 通过明确拥有的 Session 获取权限/模型配置，关闭后才调用模型；解析完成后的父任务/文件查询也使用独立 Session，关闭后才复制快照。调用方 Session 不被提交、回滚或关闭，即使其中存在已经 flush 的写入也保留。幂等命中只将 ID 带出读取会话，再由调用方读取 ORM 实例。

新增 PostgreSQL 回归验证模型和快照函数进入时所有准备查询会话均无活动事务，同时调用方已 flush 的未提交任务仍存在于原事务、对其他会话不可见，最终由调用方成功提交。PostgreSQL 32 项通过，ordinary-e2e 通过。

此改动关闭了自有查询事务跨外部操作的缺口；不声称外层组合用例的既有事务也已结束。入库前可变事实重检、路由/草稿组合阶段的完整事务范围以及提交点分类仍需继续核对，PR-02 未部署。


### 持久化前事实重检

create_run 在 prepare_run 返回新准备结果后、persist_run 之前，执行 _revalidate_prepared_run：刷新账号状态和部门、重新检查工具版本/启用状态/执行及上传权限、刷新文件记录并检查归属和内容 SHA-256、比较完整文件绑定及输入哈希、重查合并报表父任务范围。拒绝时不创建 Run/Step/Trace/Event，暂存快照作为可回收孤儿保留。既有幂等命中路径保持原行为，强幂等及全面权限收敛属于后续 PR-03/04。

PostgreSQL 36 项通过，新增停用、部门变化、版本变化和绑定变化的拒绝测试；ordinary-e2e 通过。首轮新增测试因合成未持久化 Run 未设置 parameters_json 而失败，补齐夹具后通过；未用生产数据校验。文件归属核验移至读取内容哈希之前。git diff --check 通过。

仍需完整提交点分类、端点/草稿组合边界复核及最终审查、部署验收。PR-02 未上线，不能将专项测试通过当作整阶段完成。


### 请求入口的读取/准备/写入分段

main.new_run 在认证完成后结束其拥有的请求读事务，再准备任务。main.retry 先生成纯 RunCreate 重试请求，结束其读事务，再准备及写入。assistant.confirm_draft 先由 prepare_draft_run_request 读取并冻结草稿请求，结束请求读事务后执行 prepare_run；最终 confirm_task_draft 重读草稿并比较 expected_request，变化则拒绝，未变化才将任务及草稿消费一起提交。通用服务不擅自结束调用方事务。

普通 HTTP 端到端与草稿确认 HTTP 测试在真实 _snapshot_skill 调用前断言 engine.pool.checkedout()==0，均通过，直接证明入口复制期间未持有数据库连接。事务套件 SQLite 35 通过、1 个 PG 行锁专项按方言跳过；草稿回归仍为10通过、1个已记录状态接口旧断言失败。新增接口分段尚需专项失效草稿测试及审查；PR-02 未部署。


## PR-04 聊天模型请求分段

send_workflow_message 由请求服务拥有两段事务：第一段锁后刷新身份及任务、保存用户消息并冻结决策输入，显式提交；外部模型调用期间无数据库事务和 scheduler 锁；第二段重新加锁、刷新授权与确认对象，验证后应用决定并提交。变化或撤权只阻止决策，不删除已保存的用户消息。真实PG专项验证模型期间第二连接可取得全局锁并更新任务，确认日期与确认写入两个分支均覆盖。见reports/PR-04-chat-boundary.md。


## PR-04 补取申请事务

单日与批次补取公开服务持有调度锁并负责唯一成功提交：准备函数不提交，动作/状态/消息与当前实际操作者审计一起提交；HTTP不再在服务提交后单独审计。审计异常后回滚可恢复全部补取修改，真实PG两路由用例通过。旧材料失败标记仍保留原有独立提交语义，并在授权后、补取准备前发生。见reports/PR-04-supplement-boundary.md。
