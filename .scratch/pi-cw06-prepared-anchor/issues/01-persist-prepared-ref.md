# Persist original prepared refs before effect script spawn

Status: ready-for-agent
Type: task
Blocked by: none (F4.A is accepted)
Spec: ../spec.md

Keep ArExecution.script/run_recorded_script as the behavioral seam. Implement one red/green slice at a time. First demonstrate that a separate Session cannot find the original committed ref/audit when the existing code reaches Popen; then add the minimal independent launch gate. Production edits are remote only. The regression agent owns test source; the implementation agent owns task-related backend modules; the root owns release and checkpoint records.

Completion is the spec's acceptance matrix plus deployment/runtime/read-only browser verification. No commit/push or true financial execution. Keep failures and remaining F4 scope explicit.


## Comments

2026-10-08 first red checkpoint: final stage spec f1bf99c3fdef34b56c95a94f5d5382677ba1e512288e163a2cd7b20a1bd2ad61 passed independent design Standards/Spec review with zero hard blockers. Actual caller audit confirms the standard Python workflow pool executes the three script-bearing effect handlers; Node Agent queues through API, and publication itself has no spawn.

The single first PostgreSQL test uses the real ArExecution constructor, original permissions/material/claim/safety rules, and real recorded prepared-file creation. At the Popen boundary a second independent Session observes the original intent but prepared_process_refs is empty: AssertionError 0 != 1 at test line167. One failed, 0 skipped, 1.29s. Original Popen was not called, so no child or financial script ran. Baseline runner98926aa/process evidence15eaff97; test SHA c49715866ad1d68539e5b3c7b52a1638ecdf1819ab2f03a3b15b8ffddcc422cf. Log is local .scratch/pi-construction-20260923/f4b-process-anchor-first-red-20261008.log; run window02:42:43-02:42:49 UTC, isolated tmpfs label codex-pytest-929b7f43dfac cleaned to zero.

Continuation: implementation agent may now make the minimal first happy-path slice in the three backend anchor/runner/safety modules. The test agent verifies this one case before adding further failure slices. Cancellation outcome re-fencing and sticky heartbeat latch need their own red/green slices in workflow_service before release. No F4.B green/build/deployment/browser acceptance yet; F4.A remains the accepted live release. All later full-plan scope remains active. No commit/push, real reconciliation, rerun or production financial mutation.


2026-10-08 final acceptance: frozen F4.B source and test hashes, real focused21/old67 zero-skip tests, two independent final reviews, immutable candidate build, backend-only deployment, runtime readback and fresh read-only official browser all completed. Scope and remaining work are recorded in docs/pi-cw06-prepared-anchor-progress-20261008.md, final 04:36 UTC node. No commit/push or true financial action. This issue's acceptance criteria are fulfilled; the ready-for-agent triage label remains a role, not an assertion of whole-plan completion.
