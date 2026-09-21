# PR-05 lease protocol source audit

2026-09-20. Analysis only; no lease behavior or Worker protocol changed. PR-04 and the full guide remain incomplete. The previously prepared Agent reservation candidate is still awaiting a safe deployment window.

## Confirmed source gaps

- backend/app/leases.py LeaseHeartbeat._touch restricts attempt and unexpired deadline only for ordinary Run. WorkflowAction updates match id/state/worker only; rowcount is ignored. Thus the Workflow path lacks the guide's generation and non-resurrection conditions.
- backend/app/workflow_service.py run_workflow_action_once creates LeaseHeartbeat without attempt. execute_workflow_action retains _ar_claim_worker_id but no corresponding fixed claim attempt.
- backend/app/ar_execution_runner.py lock_execution refreshes action and validates Worker, deadline and state, but does not compare the original claim attempt. Reusing the same Worker ID across attempts is not fenced by this check alone.
- backend/app/routers/pi_harness.py heartbeat_pi_harness_work checks id/name/state/Worker, then unconditionally renews deadline. It has no attempt input, expiry check or conditional update. finish_pi_harness_work uses the global lock but likewise lacks attempt and expiry checks. _assert_active_harness lacks expiry and attempt checks for tool/model/read requests.
- agent-runtime/src/workflow-harness-worker.ts heartbeat sends only worker_id; finish sends worker_id/outcome/message; model gateway fields contain workflow_id/harness_action_id/worker_id. The Worker protocol must change alongside backend validation; server-only mandatory attempt changes would break the current Worker.

These are source-confirmed missing conditions, not evidence that any actual production financial corruption occurred. No production lease was altered or replayed.

## Required coordinated implementation

1. Freeze claim attempt in Workflow execution and pass it to LeaseHeartbeat. Require same id/Worker/attempt and unexpired deadline for heartbeat and AR lock. A zero-row heartbeat must report lost eligibility without killing arbitrary processes or silently renewing later attempts.
2. Include attempt in Pi claim response and carry it through heartbeat, finish, tool requests, model gateway and result polling. Apply a protocol version compatibility gate and a coordinated API/agent release. Do not silently infer a missing attempt from the current database row.
3. Prevent stale terminal writes to a newer attempt. Preserve published evidence and unknown write outcomes; expiry does not prove the physical child exited.
4. Test same Worker different attempt, delayed heartbeat, expiry, cached ORM state, cancellation, publication/recovery races, DB outage and active subprocess. Ordinary Run fencing tests must remain intact.
5. Audit waiting_user_action capacity and retry-policy integration separately as the guide requires. This audit does not complete PR-05.
