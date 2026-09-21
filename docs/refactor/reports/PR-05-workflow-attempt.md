# PR-05 Workflow heartbeat and AR attempt slice

2026-09-20: this coordinated slice deployed and verified. PR-04/PR-05 and the full guide remain incomplete.

Workflow claim freezes _ar_claim_attempt under the global claim lock. The execution entry preserves this value, run_workflow_action_once passes it to LeaseHeartbeat, and AR lock_execution compares the frozen attempt after refreshing the action. A same-named Worker assigned a new attempt cannot pass this AR check using its old binding.

Heartbeat now requires positive attempt, matching id/Worker/attempt, running state and a still-valid deadline for both ordinary Run and WorkflowAction. It locks the target row before obtaining PostgreSQL clock_timestamp, preventing the stale-time-after-lock-wait race found in review. A zero-row result stops the heartbeat loop and exposes lease_lost; it does not kill processes or by itself fence every legacy terminal write.

Five initial regressions failed before changes; final tests include real PostgreSQL row-lock wait crossing expiry and v2 queue isolation. 104 approval-authorization plus 255 execution-authorization tests passed (359 total). The old v2 test expectation that an expired lease could be revived was replaced with valid renewal and explicit expired rejection, keeping raw state isolation assertions. Both review axes verified the final lock ordering. Static diff and candidate/recovery migration/transaction checks passed.

Candidate dfd08c178ddd was built from live 3d9e0cc0feb5, preserving the AR business base. Deployment waited for zero active tasks. API/standard Worker/discovery Worker each matched 453 hashes, UID10001, schema f4b5c6d7e8f9, restart count zero, normal mode. The image builder retains its existing PR-04 manifest/tag namespace; this report identifies the PR-05 requirement slice. Prior manifests are PR-04-image-before-workflow-attempt.json and PR-04-recovery-image-before-workflow-attempt.json.

Evidence: PR-05-workflow-attempt-{red,approval-authorization,execution-authorization,candidate-check,recovery-check,preflight,deployment,runtime-verified}.json.

Not covered: Pi HTTP/agent attempt protocol, all legacy terminal write fencing, durable lease-lost event policy, retry-policy unification, waiting_user_action capacity and complete failure matrix. SQLite does not provide PostgreSQL row-lock semantics. No actual financial task was run or interrupted, no automatic financial retry, and no dashboard modification.
