# PR-04 claim authorization observations

2026-09-20: deployed and verified. Workflow and Pi claim entrypoints now record current authorization facts with the actual action attempt in the same transaction as the running state, Worker assignment and lease. Both retain the existing global lock and final commit. Audit failure propagates without returning claimed work. No new execution privilege or commit was introduced.

Six real PostgreSQL claim tests cover workflow/Pi allowed, revoked and audit failure. Before the change, four cases failed for missing observations or absent audit-failure gating; revoked cases already passed. After the change, 83 approval-authorization and 255 execution-authorization tests passed (338 total). Two read-only reviews found no definite defect. Static diff check and candidate/recovery migration/transaction checks passed. Pi payload and fixed contract are stubbed in claim tests; these do not verify model launch or full Skill package loading.

Candidate 462dac399323 was built from live e71f8f147022 with previously merged AR updates preserved. At deployment all active task counters were zero. Runtime API/standard Worker/discovery Worker each matched 453 source hashes, schema f4b5c6d7e8f9, UID10001, restart count zero, normal mode. Recovery remains distinct replay-only core, not full old-code restoration. No dashboard modification or real financial execution.

Evidence: PR-04-claim-observation-{red,approval-authorization,execution-authorization,candidate-check,recovery-check,preflight,deployment,runtime-verified}.json. Original image manifests archived as PR-04-image-before-claim-observation.json and PR-04-recovery-image-before-claim-observation.json.

PR-04 overall remains incomplete: remaining legacy/Pi execution boundaries, complete phase/entry matrix and restricted completion before script start require audit and implementation. PR05–21 remain outstanding.
