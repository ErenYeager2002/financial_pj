# CW06 / F4.B: immutable prepared process references before spawn

Status: ready-for-agent
Date: 2026-10-08
Depends on: accepted F4.A (docs/pi-cw06-attempt-history-20261008.md)
Primary authority: user-approved financial_platform_pi_construction_standard_v1_2026-09-23.md sections 10.3, 10.7, 11.3 and 11.4.

## Problem and completion criteria

The original effect intent is durable, but prepared process references exist only in Worker memory and the latest result/failure. A Worker crash can leave an original prepared fact without its registered reference. Persist the immutable prepared reference before Popen. Recheck the current claim, lease, permissions, materials and cancellation after that commit, under the original lock order. Failed or ambiguous registration must not spawn a child.

Complete this stage only after focused red/green behavior tests, independent Standards/Spec review, required compilation/build, deployment to the existing Ubuntu release and runtime/hash/health readback, and read-only browser acceptance. Record each state separately. No real reconciliation, financial write, rerun, investigation/resolve POST, commit or push is authorized by this stage.

## Scope and existing seams

Keep the existing ArExecution.script and run_recorded_script behavior seams. This stage covers script calls made by the four existing EFFECT_PHASES through ArExecution; actual current callers are write_ledger, write_receipt_flow and complete_reconciliation. publish_reconciliation has no script spawn and retains its original publication transaction, to be tested in F5.

Do not enlarge EFFECT_PHASES or change material occupancy rules. Non-effect scripts and independent ar_business_investigation keep their current path in this stage and remain explicit F4 follow-up work. This stage does not prove that every caller/action/attempt has been adapted. No new SQL table, migration, endpoint, lock service or generic task framework.

## Internal interface and immutable reference

Add PreparedProcessAnchor as a frozen internal value with record_id, prepared_sha256, script, script_sha256, arguments_sha256, evidence schema version and an immutable prepared identity tuple (workflow/action/name/attempt/Worker/date/Skill/material/version/plan). It is constructed from the successful exclusive prepared fact and cannot be the subsequently mutated in-memory process result.

run_recorded_script accepts an optional launch_gate(anchor) context-manager callback. The effect ArExecution.script path must supply ArExecution.launch_gate; the legacy non-effect/investigation path remains explicit. Prepare command and environment before entering the second lock window. Enter the gate after prepared.json exclusive write, flush and fsync. Only Popen and minimal started identity/fact writing are inside its yield. communicate, process termination, waits and descendant receipt verification occur after the gate releases its database locks, including exception paths.

Append prepared_process_refs to the original execution_safety_v1 attempt entry. Each reference contains exactly:

```text
schema_version = ar-process-evidence-v1
record_id = 32 lowercase hexadecimal characters
prepared_sha256 = 64 lowercase hexadecimal characters
script = fixed snapshot script basename
script_sha256 = 64 lowercase hexadecimal characters
arguments_sha256 = 64 lowercase hexadecimal characters
binding_sha256 = the original safety attempt binding digest
registered_at = UTC ISO timestamp
```

Do not store paths, PID, host, raw arguments or script output in this reference. It is append-only: no overwrite, replacement or deletion of previous bindings/refs to create room. Across all attempts of one action, at most 128 references, matching existing process inspection capacity. Duplicate record IDs, digest/binding conflicts, invalid persisted refs, incomplete identity or capacity overflow reject a new spawn. An already registered reference is not permission to launch again. The original entry must be the unique intent_recorded entry for the pinned action/attempt/phase/Worker and match all original input binding fields.

AuditEvent action is ar_process_prepared_registered, resource_type workflow and resource_id workflow.id. Details are limited to action_id, attempt, phase, record_id, prepared_sha256, binding_sha256 and evidence_revision. Append the audit and reference, increment the original index revision, and commit them together. Authorization observation uses the existing mechanism without storing private material data.

## Transaction and claim ownership

Use a short-lived Session on the same Engine with an independent physical connection. Never borrow the caller Connection or treat SQLite StaticPool as isolated. The gate must not commit or rollback the caller Session, including previously flushed business changes. Existing authorized outer publication/completion commits remain their own responsibility. Effect script routing must avoid the old script-entry lock_execution implicit commit. Do not add a generic pending-DML detector. Arbitrary conflicting caller writes are not promised to execute successfully; they must not be silently committed to unblock the gate.

First transaction: acquire existing global claim lock, then action FOR UPDATE; reload current action/workflow, observe database time after locks (PostgreSQL clock_timestamp), check the pinned claim and original binding, current permission/material and existing cancellation policy. Append refs and AuditEvent atomically; commit. A commit exception or response-loss outcome denies Popen, even if the database may have committed.

Second transaction: reacquire global then action lock, reload current objects and read database time after locks. Recheck current action state, positive pinned attempt, Worker, unexpired lease, workflow eligibility, cancellation, current permission/material and the exact registered original anchor. After the guards finish, immediately before yielding to Popen, read PostgreSQL clock_timestamp again and recheck the lease and sticky loss flag. Hold the short lock through Popen and started fact only. Never use caller stale ORM values or a prior transaction timestamp as authorization. No global lock during script communicate/wait/termination. Later transition must retain registered refs when refreshing the authoritative context. This second transaction is read-only: observe_phase=None, no authorization observation or business DML. Explicitly rollback and close this independent Session before communicate or cleanup. Use a local bounded lock wait of at most two seconds, preserving any stricter existing limit; lock timeout rejects spawn and never commits or rolls back the caller to unblock it.

Reuse original complete_reconciliation cancellation exception only where already permitted; do not broaden it. A gate cancellation exception leaves its independent locks released. The outer workflow_service cancellation handler must not assume that it still holds the claim lock: for an AR action without its current outer lock, it rolls back its own unfinished phase transaction, reacquires global then action locks and freshly verifies the pinned Worker/attempt and post-lock PostgreSQL clock/lease before saving cancellation. If ownership was lost, rollback the outer transaction, set the existing lease-lost outcome and do not overwrite the new owner. Existing publication cancellation already holding its outer lock retains that transaction. This is an outer Worker outcome responsibility; launch_gate still never commits or rolls back its caller. Initialize the in-memory lease-lost flag once before heartbeat starts, mark it on every lease-loss callback even between scripts, and never reset it at a later script start. A known lost lease rejects the next spawn. Lock-time validity proves ownership of this launch decision, not a claim that wall-clock expiry can never happen while OS scheduling proceeds.

## Focused acceptance matrix

1. Through real ArExecution.script and real recorded-process path, a separate PostgreSQL Session at Popen observes the committed original prepared reference and its matching audit. Use a synthetic no-op script, never a workbook writer.
2. Prepared/fact or anchor/Audit commit failure, including ambiguous commit response, results in zero Popen calls. No partial ref/audit commit, erased old intent or automatic replay.
3. Cancellation or lease/attempt/Worker/binding change between transactions prevents spawn and preserves original registered facts; permission and material are rechecked on fresh gate objects.
4. A real PostgreSQL action-lock wait that crosses the deadline uses clock_timestamp after acquiring both locks and prevents spawn. SQLite does not prove this race.
5. Caller flushed but uncommitted unrelated DML is not committed/rolled back by the gate and can still be rolled back by the caller. Conflicting caller locks must fail safely without a hidden caller commit.
6. Duplicate record registration/relaunch, malformed refs, hash/binding conflict and the 128/129 action record boundary reject spawn without overwriting earlier attempts or adding duplicate audit/revision changes.
7. Heartbeat lease loss between scripts remains sticky and prevents the next script, with a targeted real wiring regression.
8. Popen failure and started fact failure preserve the anchor; after a real child is launched, cleanup releases database locks before termination/wait. communicate also runs without those locks.
9. Normal successful phase transition preserves the durable anchor; a later failure/attempt cannot erase it. Old valid entries without the optional refs and legacy non-effect/investigation signatures remain compatible.
10. Targeted static/compile checks and F4.A/F1/F2 regressions pass as applicable; candidate and deployed protected file hashes match, live health/normal state and browser history/old unknown warning remain. No real task mutation is used to manufacture acceptance.

## Conservative conclusions and remaining work

Database registration and Popen are not atomic; this is not exactly-once execution. Prepared refs never prove no spawn, exit, no effect, successful business result or released occupancy. Missing started/terminal fact, ambiguous commit, power loss or missing directory remains unknown. File fsync alone does not establish parent-directory crash durability; missing facts remain a visible investigation gap. Terminal refs and complete multi-attempt directory/worker/external/business proof, historical investigation and conditional administrator disposition remain later F4 work. Publication crash testing remains F5. Do not repair historical refs by scanning files and pretending they were originally registered.


## Acceptance record


2026-10-08 final acceptance: frozen F4.B source and test hashes, real focused21/old67 zero-skip tests, two independent final reviews, immutable candidate build, backend-only deployment, runtime readback and fresh read-only official browser all completed. Scope and remaining work are recorded in docs/pi-cw06-prepared-anchor-progress-20261008.md, final 04:36 UTC node. No commit/push or true financial action. This issue's acceptance criteria are fulfilled; the ready-for-agent triage label remains a role, not an assertion of whole-plan completion.
