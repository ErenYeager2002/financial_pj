# Execution entrypoints

Baseline `2cd58e91348ff566250f03b882f22c46425bbe1f`. Static AST evidence only; dynamic dispatch, imported aliases and runtime reachability require targeted verification.

Every decorator route is listed below, including test fixtures. This is not a complete runtime call graph. See [call sites](reports/python-call-sites.md) for caller scopes. Router prefixes, registration, worker loops, Pi and Native runtime traces remain to be annotated before PR-00 acceptance.

| File | Line | Verb | Decorator path | Handler |
|---|---|---|---|---|
| backend/app/main.py | 306 | get | /api/health | health |
| backend/app/main.py | 319 | get | /api/health/readiness | health_readiness |
| backend/app/main.py | 328 | get | /api/session | session |
| backend/app/main.py | 348 | get | /api/skills | list_skills |
| backend/app/main.py | 365 | get | /api/skills/{skill_id} | get_skill |
| backend/app/main.py | 402 | get | /api/catalog/skills | list_catalog_skills |
| backend/app/main.py | 413 | get | /api/catalog/skill-summaries | list_catalog_skill_summaries |
| backend/app/main.py | 426 | get | /api/catalog/skills/{skill_id} | get_catalog_skill |
| backend/app/main.py | 443 | post | /api/skills/{skill_id}/interpret | interpret |
| backend/app/main.py | 469 | get | /api/model-connections | model_connections |
| backend/app/main.py | 477 | get | /api/model-providers | model_providers |
| backend/app/main.py | 484 | post | /api/model-connections | connect_model |
| backend/app/main.py | 503 | patch | /api/model-connections/{connection_id} | update_model |
| backend/app/main.py | 516 | post | /api/model-connections/{connection_id}/refresh | refresh_model |
| backend/app/main.py | 525 | delete | /api/model-connections/{connection_id} | delete_model |
| backend/app/main.py | 537 | get | /api/service-credentials/{service} | service_credential |
| backend/app/main.py | 549 | put | /api/service-credentials/{service} | update_service_credential |
| backend/app/main.py | 559 | delete | /api/service-credentials/{service} | delete_service_credential |
| backend/app/main.py | 568 | post | /api/files | upload_file |
| backend/app/main.py | 621 | get | /api/files | list_files |
| backend/app/main.py | 663 | get | /api/files/groups | list_file_group_summaries |
| backend/app/main.py | 688 | get | /api/files/selectable-inputs | list_selectable_input_files |
| backend/app/main.py | 724 | get | /api/files/{file_id} | get_file |
| backend/app/main.py | 733 | get | /api/files/{file_id}/download | download_file |
| backend/app/main.py | 766 | delete | /api/files/{file_id} | remove_uploaded_file |
| backend/app/main.py | 796 | post | /api/runs | new_run |
| backend/app/main.py | 806 | get | /api/workflows | workflows |
| backend/app/main.py | 816 | post | /api/workflows | new_workflow |
| backend/app/main.py | 825 | post | /api/workflows/start | start_workflow_session |
| backend/app/main.py | 840 | get | /api/workflow-batches | workflow_batches |
| backend/app/main.py | 864 | post | /api/workflow-batches/start | start_workflow_batch_session |
| backend/app/main.py | 879 | get | /api/workflow-batches/{batch_id} | get_workflow_batch |
| backend/app/main.py | 890 | post | /api/workflow-batches/{batch_id}/retry | retry_workflow_batch_session |
| backend/app/main.py | 901 | post | /api/workflow-batches/{batch_id}/cancel | cancel_workflow_batch_session |
| backend/app/main.py | 913 | get | /api/workflow-batches/{batch_id}/fetched-data | get_workflow_batch_fetched_data |
| backend/app/main.py | 937 | post | /api/workflow-batches/{batch_id}/fetched-data/confirm | confirm_workflow_batch_fetched_data |
| backend/app/main.py | 961 | post | /api/workflow-batches/{batch_id}/fetched-data/supplement | supplement_workflow_batch_fetched_data |
| backend/app/main.py | 993 | post | /api/workflows/{workflow_id}/cancel | cancel_workflow_session |
| backend/app/main.py | 1002 | get | /api/workflows/material-edit-state | get_material_edit_state |
| backend/app/main.py | 1013 | delete | /api/workflows/reusable-files | remove_reusable_workflow_files |
| backend/app/main.py | 1033 | get | /api/workflows/reusable-files | get_reusable_workflow_files |
| backend/app/main.py | 1053 | get | /api/workflows/fetched-snapshots | get_fetched_snapshot_options |
| backend/app/main.py | 1062 | get | /api/workflows/material-sets | get_workflow_material_sets |
| backend/app/main.py | 1079 | post | /api/workflows/material-sets/{material_set_id}/restore | restore_workflow_material_set |
| backend/app/main.py | 1111 | get | /api/workflows/{workflow_id} | get_workflow |
| backend/app/main.py | 1120 | get | /api/workflows/{workflow_id}/execution | get_workflow_execution |
| backend/app/main.py | 1129 | post | /api/workflows/{workflow_id}/execution/recover | recover_workflow_execution |
| backend/app/main.py | 1142 | post | /api/workflows/{workflow_id}/execution/investigate | investigate_failed_workflow_write |
| backend/app/main.py | 1157 | get | /api/workflows/{workflow_id}/result-details | get_workflow_result_details |
| backend/app/main.py | 1169 | get | /api/workflow-batches/{batch_id}/result-details | get_batch_result_details |
| backend/app/main.py | 1185 | get | /api/workflows/{workflow_id}/order-evidence | get_workflow_order_evidence |
| backend/app/main.py | 1203 | get | /api/workflows/{workflow_id}/fetched-data | get_workflow_fetched_data |
| backend/app/main.py | 1223 | post | /api/workflows/{workflow_id}/fetched-data/confirm | confirm_workflow_fetched_data |
| backend/app/main.py | 1247 | post | /api/workflows/{workflow_id}/fetched-data/supplement | supplement_workflow_fetched_data |
| backend/app/main.py | 1280 | post | /api/workflows/{workflow_id}/agent/actions | workflow_agent_action |
| backend/app/main.py | 1309 | get | /api/workflows/{workflow_id}/agent/context | workflow_agent_context |
| backend/app/main.py | 1333 | put | /api/workflows/{workflow_id}/files | set_workflow_files |
| backend/app/main.py | 1347 | post | /api/workflows/{workflow_id}/messages | workflow_message |
| backend/app/main.py | 1365 | post | /api/workflows/{workflow_id}/confirm | confirm_workflow_result |
| backend/app/main.py | 1378 | post | /api/workflows/{workflow_id}/rebuild | rebuild_workflow_result |
| backend/app/main.py | 1392 | post | /api/workflows/{workflow_id}/reset | reset_workflow_session |
| backend/app/main.py | 1402 | get | /api/workbench | workbench |
| backend/app/main.py | 1410 | get | /api/runs | list_runs |
| backend/app/main.py | 1436 | get | /api/task-center | list_task_center_items |
| backend/app/main.py | 1467 | get | /api/runs/{run_id} | get_run |
| backend/app/main.py | 1478 | get | /api/runs/{run_id}/steps | get_run_steps |
| backend/app/main.py | 1487 | get | /api/runs/{run_id}/approvals | get_run_approvals |
| backend/app/main.py | 1496 | get | /api/runs/{run_id}/event-history | get_run_event_history |
| backend/app/main.py | 1526 | post | /api/runs/{run_id}/retry | retry |
| backend/app/main.py | 1546 | post | /api/runs/{run_id}/confirm | confirm |
| backend/app/main.py | 1558 | post | /api/runs/{run_id}/cancel | cancel |
| backend/app/main.py | 1576 | get | /api/runs/{run_id}/events | run_events |
| backend/app/main.py | 1627 | post | /api/admin/registry/reload | reload_registry |
| backend/app/main.py | 1644 | get | /docs | docs_ui |
| backend/app/main.py | 1649 | get | /redoc | redoc_ui |
| backend/app/main.py | 1654 | get | /openapi.json | openapi_json |
| backend/app/main.py | 1664 | get | /{path:path} | spa |
| backend/app/main.py | 1673 | get | / | api_root |
| backend/app/pi_business_query.py | 57 | post | /platform/query | query |
| backend/app/pi_business_query.py | 75 | post | /platform/skill-proposal | proposal |
| backend/app/pi_model_broker.py | 89 | post | /v1/chat/completions | completions |
| backend/app/routers/admin_approvals.py | 15 | get |  | admin_list_approvals |
| backend/app/routers/admin_approvals.py | 28 | post | /{approval_id}/decision | admin_decide_approval |
| backend/app/routers/admin_observability.py | 15 | get | /api/admin/observability/summary | admin_observability_summary |
| backend/app/routers/admin_skill_dedications.py | 19 | get |  | admin_list_skill_dedications |
| backend/app/routers/admin_skill_dedications.py | 28 | put | /{skill_id} | admin_set_skill_dedication |
| backend/app/routers/admin_skill_dedications.py | 39 | delete | /{skill_id} | admin_clear_skill_dedication |
| backend/app/routers/admin_skills.py | 54 | post | /skill-releases/{release_id}/rollout | admin_start_skill_rollout |
| backend/app/routers/admin_skills.py | 65 | get | /skill-rollouts/{rollout_id} | admin_get_skill_rollout |
| backend/app/routers/admin_skills.py | 75 | get | /availability | admin_list_skill_availability |
| backend/app/routers/admin_skills.py | 84 | get | /{skill_id}/availability | admin_get_skill_availability |
| backend/app/routers/admin_skills.py | 94 | post | /{skill_id}/availability | admin_transition_skill_availability |
| backend/app/routers/admin_skills.py | 105 | get | /bindings | admin_list_skill_source_bindings |
| backend/app/routers/admin_skills.py | 114 | post | /discover | admin_discover_skill_sources |
| backend/app/routers/admin_skills.py | 124 | post | /bindings | admin_confirm_skill_source_binding |
| backend/app/routers/admin_skills.py | 138 | post | /bindings/{skill_id}/check-update | admin_check_skill_source_update |
| backend/app/routers/admin_skills.py | 152 | post | /bindings/{skill_id}/prepare-release | admin_prepare_bound_skill_release |
| backend/app/routers/admin_skills.py | 163 | post | /{skill_id}/update | admin_update_disabled_skill |
| backend/app/routers/admin_skills.py | 173 | get | /inbox | admin_list_release_inbox |
| backend/app/routers/admin_skills.py | 182 | get |  | admin_list_skill_releases |
| backend/app/routers/admin_skills.py | 192 | post | /import | admin_import_skill_release |
| backend/app/routers/admin_skills.py | 202 | patch | /{release_id} | admin_update_skill_release |
| backend/app/routers/admin_skills.py | 213 | post | /{release_id}/review | admin_review_skill_release |
| backend/app/routers/admin_skills.py | 224 | post | /{release_id}/publish | admin_publish_skill_release |
| backend/app/routers/admin_skills.py | 239 | post | /install-catalog | admin_install_catalog |
| backend/app/routers/admin_skills.py | 245 | post | /prepare-install | admin_prepare_install |
| backend/app/routers/admin_users.py | 30 | get |  | admin_list_users |
| backend/app/routers/admin_users.py | 39 | post |  | admin_create_user |
| backend/app/routers/admin_users.py | 49 | patch | /{user_id} | admin_update_user |
| backend/app/routers/admin_users.py | 60 | delete | /{user_id} | admin_delete_user |
| backend/app/routers/admin_users.py | 71 | post | /{user_id}/reset-password | admin_reset_user_password |
| backend/app/routers/admin_users.py | 84 | put | /{user_id}/skill-permissions | admin_replace_skill_permissions |
| backend/app/routers/admin_workflows.py | 18 | get | /api/admin/workflow-definitions | admin_list_workflow_definitions |
| backend/app/routers/assistant.py | 68 | get | /api/assistant/skills/{skill_id}/instructions | assistant_skill_instructions |
| backend/app/routers/assistant.py | 92 | get | /api/assistant/conversations | assistant_conversations |
| backend/app/routers/assistant.py | 106 | get | /api/assistant/conversations/latest | latest_assistant_conversation |
| backend/app/routers/assistant.py | 117 | get | /api/assistant/conversations/{session_id} | assistant_conversation |
| backend/app/routers/assistant.py | 130 | post | /api/assistant/conversations/{session_id}/messages | append_assistant_conversation_message |
| backend/app/routers/assistant.py | 161 | post | /api/assistant/model/chat/completions | stream_agent_model |
| backend/app/routers/assistant.py | 161 | post | /api/assistant/model | stream_agent_model |
| backend/app/routers/assistant.py | 219 | get | /api/assistant/status | get_assistant_status |
| backend/app/routers/assistant.py | 227 | get | /api/assistant/skills | list_assistant_skills |
| backend/app/routers/assistant.py | 236 | post | /api/assistant/prepare-from-recommendation | prepare_from_agent_recommendation |
| backend/app/routers/assistant.py | 267 | post | /api/assistant/prepare | prepare |
| backend/app/routers/assistant.py | 290 | get | /api/task-drafts/{draft_id} | get_draft |
| backend/app/routers/assistant.py | 299 | patch | /api/task-drafts/{draft_id} | update_draft |
| backend/app/routers/assistant.py | 319 | post | /api/task-drafts/{draft_id}/confirm | confirm_draft |
| backend/app/routers/assistant.py | 338 | delete | /api/task-drafts/{draft_id} | delete_draft |
| backend/app/routers/assistant.py | 356 | get | /api/admin/assistant-profile | get_admin_profile |
| backend/app/routers/assistant.py | 365 | put | /api/admin/assistant-profile | put_admin_profile |
| backend/app/routers/assistant.py | 384 | delete | /api/admin/assistant-profile | delete_admin_profile |
| backend/app/routers/assistant.py | 401 | get | /api/assistant/ar/materials | assistant_ar_materials |
| backend/app/routers/assistant.py | 407 | post | /api/assistant/ar/prepare | assistant_ar_prepare |
| backend/app/routers/assistant.py | 413 | post | /api/assistant/ar/start | assistant_ar_start |
| backend/app/routers/assistant.py | 419 | get | /api/assistant/ar/task | assistant_ar_task |
| backend/app/routers/assistant.py | 425 | get | /api/assistant/ar/request | assistant_ar_request_status |
| backend/app/routers/assistant.py | 435 | get | /api/native-skills | native_skill_list |
| backend/app/routers/assistant.py | 439 | get | /api/native-skills/{skill_id} | native_skill_detail |
| backend/app/routers/assistant.py | 444 | post | /api/assistant/native-skills/{skill_id}/context | native_skill_context |
| backend/app/routers/assistant.py | 448 | get | /api/assistant/native-skills/{skill_id}/file | native_skill_file |
| backend/app/routers/assistant.py | 452 | post | /api/assistant/native-skills/{skill_id}/command | native_skill_command |
| backend/app/routers/assistant.py | 457 | get | /api/assistant/native-skills/{skill_id}/runs | native_skill_runs |
| backend/app/routers/assistant.py | 464 | get | /api/assistant/turns/{session_id} | persisted_turn_status |
| backend/app/routers/assistant.py | 468 | post | /api/assistant/turns/{session_id} | persisted_turn_mutation |
| backend/app/routers/audit.py | 42 | get |  | list_audit_events |
| backend/app/routers/audit.py | 92 | get | /page | list_audit_event_page |
| backend/app/routers/auth.py | 56 | post | /login | auth_login |
| backend/app/routers/auth.py | 88 | post | /change-password | auth_change_password |
| backend/app/routers/auth.py | 120 | post | /logout | auth_logout |
| backend/app/routers/auth.py | 140 | get | /session | auth_session |
| backend/app/routers/pi_harness.py | 380 | post | /claim | claim_pi_harness_work |
| backend/app/routers/pi_harness.py | 487 | post | /actions/{action_id}/heartbeat | heartbeat_pi_harness_work |
| backend/app/routers/pi_harness.py | 509 | post | /actions/{action_id}/finish | finish_pi_harness_work |
| backend/app/routers/pi_harness.py | 571 | post | /workflows/{workflow_id}/tools/{tool_name} | request_pi_harness_tool |
| backend/app/routers/pi_harness.py | 694 | get | /workflows/{workflow_id}/actions/{action_id} | read_pi_harness_tool |
| backend/app/routers/pi_harness.py | 723 | post | /model/chat/completions | stream_pi_harness_model |
| backend/app/routers/pi_runtime.py | 30 | get | /sessions | list_sessions |
| backend/app/routers/pi_runtime.py | 35 | post | /sessions | create_session |
| backend/app/routers/pi_runtime.py | 46 | post | /sessions/{session_id}/operate | operate |
| backend/app/routers/pi_runtime.py | 87 | post | /sessions/{session_id}/files | files |
| backend/app/routers/pi_runtime.py | 100 | get | /sessions/{session_id}/download | download |
| backend/app/routers/pi_runtime.py | 128 | get | /skill-proposals | proposals |
| backend/app/routers/pi_runtime.py | 134 | post | /skill-proposals/{candidate_id}/publish | publish_candidate |
| backend/app/routers/profile.py | 31 | post | /avatar | upload_avatar |
| backend/app/routers/profile.py | 50 | get | /avatar | get_avatar |
| backend/app/routers/task_reminders.py | 38 | get |  | list_task_reminders |
| backend/app/routers/task_reminders.py | 46 | delete | /resolved | clear_resolved_task_reminders |
| backend/app/routers/task_reminders.py | 54 | post | /checks | queue_task_discovery_check |
| backend/app/routers/task_reminders.py | 63 | post | /checks/{check_id}/retry | retry_task_discovery_check |
| backend/app/routers/task_reminders.py | 72 | get | /{skill_id} | admin_get_task_reminder_subscription |
| backend/app/routers/task_reminders.py | 82 | put | /{skill_id} | admin_save_task_reminder_subscription |
| backend/app/routers/task_reminders.py | 93 | get | /{skill_id}/credential | admin_get_task_reminder_owner_credential |
| backend/app/routers/task_reminders.py | 103 | put | /{skill_id}/credential | admin_save_task_reminder_owner_credential |
| backend/app/routers/task_reminders.py | 120 | delete | /{skill_id}/credential | admin_delete_task_reminder_owner_credential |

## Frontend entries

| File | Route entry | BFF |
|---|---|---|
| web/src/app/api/auth/change-password/route.ts | True | True |
| web/src/app/api/auth/login/route.ts | True | True |
| web/src/app/api/auth/logout/route.ts | True | True |
| web/src/app/api/auth/session/route.ts | True | True |
| web/src/app/api/platform/admin/approvals/[approvalId]/decision/route.ts | True | True |
| web/src/app/api/platform/admin/approvals/route.ts | True | True |
| web/src/app/api/platform/admin/assistant-profile/route.ts | True | True |
| web/src/app/api/platform/admin/audit-events/page/route.ts | True | True |
| web/src/app/api/platform/admin/audit-events/route.ts | True | True |
| web/src/app/api/platform/admin/model-connections/[connectionId]/refresh/route.ts | True | True |
| web/src/app/api/platform/admin/model-connections/[connectionId]/route.ts | True | True |
| web/src/app/api/platform/admin/model-connections/providers/route.ts | True | True |
| web/src/app/api/platform/admin/model-connections/route.ts | True | True |
| web/src/app/api/platform/admin/observability/summary/route.ts | True | True |
| web/src/app/api/platform/admin/skill-dedications/[skillId]/route.ts | True | True |
| web/src/app/api/platform/admin/skill-dedications/route.ts | True | True |
| web/src/app/api/platform/admin/skill-releases/[releaseId]/publish/route.ts | True | True |
| web/src/app/api/platform/admin/skill-releases/[releaseId]/review/route.ts | True | True |
| web/src/app/api/platform/admin/skill-releases/[releaseId]/rollout/route.ts | True | True |
| web/src/app/api/platform/admin/skill-releases/[releaseId]/route.ts | True | True |
| web/src/app/api/platform/admin/skill-releases/import/route.ts | True | True |
| web/src/app/api/platform/admin/skill-releases/inbox/route.ts | True | True |
| web/src/app/api/platform/admin/skill-releases/route.ts | True | True |
| web/src/app/api/platform/admin/skill-rollouts/[rolloutId]/route.ts | True | True |
| web/src/app/api/platform/admin/skill-sources/bindings/[skillId]/check-update/route.ts | True | True |
| web/src/app/api/platform/admin/skill-sources/bindings/[skillId]/prepare-release/route.ts | True | True |
| web/src/app/api/platform/admin/skill-sources/bindings/route.ts | True | True |
| web/src/app/api/platform/admin/skill-sources/discover/route.ts | True | True |
| web/src/app/api/platform/admin/skill-sources/install-catalog/route.ts | True | True |
| web/src/app/api/platform/admin/skill-sources/prepare-install/route.ts | True | True |
| web/src/app/api/platform/admin/skills/[skillId]/availability/route.ts | True | True |
| web/src/app/api/platform/admin/skills/[skillId]/update/route.ts | True | True |
| web/src/app/api/platform/admin/skills/availability/route.ts | True | True |
| web/src/app/api/platform/admin/task-reminder-subscriptions/[skillId]/credential/route.ts | True | True |
| web/src/app/api/platform/admin/task-reminder-subscriptions/[skillId]/route.ts | True | True |
| web/src/app/api/platform/admin/users/[userId]/reset-password/route.ts | True | True |
| web/src/app/api/platform/admin/users/[userId]/route.ts | True | True |
| web/src/app/api/platform/admin/users/[userId]/skill-permissions/route.ts | True | True |
| web/src/app/api/platform/admin/users/route.ts | True | True |
| web/src/app/api/platform/admin/workflow-definitions/route.ts | True | True |
| web/src/app/api/platform/assistant/conversations/[sessionId]/route.ts | True | True |
| web/src/app/api/platform/assistant/conversations/latest/route.ts | True | True |
| web/src/app/api/platform/assistant/conversations/route.ts | True | True |
| web/src/app/api/platform/assistant/native-skills/[skillId]/runs/route.ts | True | True |
| web/src/app/api/platform/assistant/prepare/route.ts | True | True |
| web/src/app/api/platform/assistant/status/route.ts | True | True |
| web/src/app/api/platform/assistant/turn/route.ts | True | True |
| web/src/app/api/platform/files/[fileId]/download/route.ts | True | True |
| web/src/app/api/platform/files/[fileId]/route.ts | True | True |
| web/src/app/api/platform/files/groups/route.ts | True | True |
| web/src/app/api/platform/files/route.ts | True | True |
| web/src/app/api/platform/files/selectable-inputs/route.ts | True | True |
| web/src/app/api/platform/pi-runtime/sessions/[sessionId]/download/route.ts | True | True |
| web/src/app/api/platform/pi-runtime/sessions/[sessionId]/files/route.ts | True | True |
| web/src/app/api/platform/pi-runtime/sessions/[sessionId]/operate/route.ts | True | True |
| web/src/app/api/platform/pi-runtime/sessions/route.ts | True | True |
| web/src/app/api/platform/pi-runtime/skill-proposals/[candidateId]/publish/route.ts | True | True |
| web/src/app/api/platform/pi-runtime/skill-proposals/route.ts | True | True |
| web/src/app/api/platform/profile/avatar/route.ts | True | True |
| web/src/app/api/platform/runs/[runId]/approvals/route.ts | True | True |
| web/src/app/api/platform/runs/[runId]/confirm/route.ts | True | True |
| web/src/app/api/platform/runs/[runId]/events/route.ts | True | True |
| web/src/app/api/platform/runs/[runId]/files/[fileId]/route.ts | True | True |
| web/src/app/api/platform/runs/[runId]/retry/route.ts | True | True |
| web/src/app/api/platform/runs/[runId]/route.ts | True | True |
| web/src/app/api/platform/runs/[runId]/steps/route.ts | True | True |
| web/src/app/api/platform/runs/route.ts | True | True |
| web/src/app/api/platform/service-credentials/[service]/route.ts | True | True |
| web/src/app/api/platform/session/route.ts | True | True |
| web/src/app/api/platform/skills/[skillId]/route.ts | True | True |
| web/src/app/api/platform/skills/route.ts | True | True |
| web/src/app/api/platform/task-center/route.ts | True | True |
| web/src/app/api/platform/task-drafts/[draftId]/confirm/route.ts | True | True |
| web/src/app/api/platform/task-drafts/[draftId]/route.ts | True | True |
| web/src/app/api/platform/task-reminders/checks/[checkId]/retry/route.ts | True | True |
| web/src/app/api/platform/task-reminders/route.ts | True | True |
| web/src/app/api/platform/workbench/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/[batchId]/cancel/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/[batchId]/fetched-data/confirm/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/[batchId]/fetched-data/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/[batchId]/fetched-data/supplement/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/[batchId]/result-details/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/[batchId]/retry/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/[batchId]/route.ts | True | True |
| web/src/app/api/platform/workflow-batches/start/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/agent/turn/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/cancel/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/confirm/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/execution/investigate/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/execution/recover/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/execution/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/fetched-data/confirm/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/fetched-data/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/fetched-data/supplement/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/files/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/messages/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/order-evidence/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/rebuild/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/result-details/route.ts | True | True |
| web/src/app/api/platform/workflows/[workflowId]/route.ts | True | True |
| web/src/app/api/platform/workflows/fetched-snapshots/route.ts | True | True |
| web/src/app/api/platform/workflows/material-edit-state/route.ts | True | True |
| web/src/app/api/platform/workflows/material-sets/[materialSetId]/restore/route.ts | True | True |
| web/src/app/api/platform/workflows/material-sets/route.ts | True | True |
| web/src/app/api/platform/workflows/reusable-files/route.ts | True | True |
| web/src/app/api/platform/workflows/route.ts | True | True |
| web/src/app/api/platform/workflows/start/route.ts | True | True |
| web/src/app/auth/change-password/page.tsx | True | False |
| web/src/app/auth/page.tsx | True | False |
| web/src/app/auth/sign-in/[[...sign-in]]/page.tsx | True | False |
| web/src/app/auth/sign-up/[[...sign-up]]/page.tsx | True | False |
| web/src/app/dashboard/ai-chat/page.tsx | True | False |
| web/src/app/dashboard/files/[fileId]/page.tsx | True | False |
| web/src/app/dashboard/files/page.tsx | True | False |
| web/src/app/dashboard/installed-skills/[skillId]/page.tsx | True | False |
| web/src/app/dashboard/installed-skills/[skillId]/run/page.tsx | True | False |
| web/src/app/dashboard/installed-skills/page.tsx | True | False |
| web/src/app/dashboard/model-connections/page.tsx | True | False |
| web/src/app/dashboard/overview/page.tsx | True | False |
| web/src/app/dashboard/page.tsx | True | False |
| web/src/app/dashboard/pi/page.tsx | True | False |
| web/src/app/dashboard/profile/[[...profile]]/page.tsx | True | False |
| web/src/app/dashboard/runs/[runId]/page.tsx | True | False |
| web/src/app/dashboard/runs/page.tsx | True | False |
| web/src/app/dashboard/skill-governance/page.tsx | True | False |
| web/src/app/dashboard/skill-reviews/page.tsx | True | False |
| web/src/app/dashboard/skills/[skillId]/page.tsx | True | False |
| web/src/app/dashboard/skills/[skillId]/run/page.tsx | True | False |
| web/src/app/dashboard/skills/[skillId]/tasks/[taskId]/page.tsx | True | False |
| web/src/app/dashboard/skills/page.tsx | True | False |
| web/src/app/dashboard/users/page.tsx | True | False |
| web/src/app/dashboard/workflows/[workflowId]/page.tsx | True | False |
| web/src/app/dashboard/workflows/batches/[batchId]/page.tsx | True | False |
| web/src/app/dashboard/workflows/page.tsx | True | False |
| web/src/app/page.tsx | True | False |
