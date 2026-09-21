# PR-05 Pi execution-attempt protocol

Status: deployed and runtime verified on 2026-09-21. PR-05 remains incomplete.

The claim request requires pi-harness-attempt-v1; its response binds a positive immutable attempt. Heartbeat, tool requests, model requests, action reads and completion carry that attempt and explicit harness identity. The shared validator takes the existing global lock followed by the action row lock, refreshes database state, and checks PostgreSQL clock_timestamp after locking. Missing, stale, expired and wrong-worker requests cannot renew or finish the action. Budget reservation and both legacy and phased tool queues repeat the check at their authoritative boundary. Read tools recheck the attempt and current owner before success audit.

The actual TypeScript Worker passes the claim attempt through all those routes. The model gateway preserves its numeric type. Compiled runtime comparison changes only workflow-harness-worker.js/map and the model adapter declaration; other compiled modules match the prior Agent image.

Verification: 31 isolated PostgreSQL/HTTP protocol tests, 108 approval/authorization tests, 255 execution-authorization tests and 8 Agent tests passed. The Agent tests include a real compiled Worker process against a synthetic loopback API/model. The 57 deployment tests and paired read-only release preflight passed. Candidate and replay-only recovery images passed schema and transaction checks. 204 backend files match the build source; 250 AR Skill files are inherited unchanged from the live immutable image (not rebuilt from the local Skill directories). No real model request, financial execution, write, commit or push was initiated by this slice.

Concurrent releases were preserved: formal-ledger staging scope validation and restricted completion of immutable historical publications. Production base before this release is recorded in PR-05-pi-release-binding.json. Source changes after binding or a changed live base require revalidation/rebuild before apply.

Prepared image IDs, hash binding, tests and current wait evidence are in PR-05-pi-release-binding.json, PR-05-pi-attempt-tests.json, PR-05-pi-attempt-approval-authorization-check.json, PR-05-pi-attempt-execution-authorization.json, PR-05-pi-agent-tests.json, PR-05-pi-release-preflight.json and PR-05-pi-release-wait.json. Deployment must use candidate backend + prepared Agent together; the replay-only recovery backend uses the same new Agent protocol. It is a restricted recovery, not a full old-code rollback.

Still pending in PR-05: transient heartbeat retry policy, full legacy terminal fencing, common retry policy and the rest of the guide's failure matrix. Full PR00–PR21 goal remains open.

Deployment evidence: PR-05-pi-release-deployment.json and PR-05-pi-runtime-verified.json. All three backend services match 454 bound file hashes; Agent matches 18 compiled file hashes; invalid protocol/attempt probes return 422 and synthetic nonexistent lease returns 409. Public/internal maintenance returned to normal. The concurrent ordinary material rebinding fix was preserved and passed 14 focused tests. No real financial task was started or retried.
