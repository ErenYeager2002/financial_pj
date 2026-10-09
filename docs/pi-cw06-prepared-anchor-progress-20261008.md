# CW06 / F4.B partial implementation and continuation

2026-10-08 03:00 UTC checkpoint. Overall construction remains active. This is an implementation/testing node, not delivery, deployment or a pause. User token preference is based on context capacity: preserve a node and continuation near the context limit, without choosing a numeric token budget.

## Authority and accepted baseline

Approved full plan remains financial_platform_pi_construction_standard_v1_2026-09-23.md. F4.A is accepted and live; this stage does not shrink the final all-action/all-attempt target. Stage contract .scratch/pi-cw06-prepared-anchor/spec.md SHA f1bf99c3fdef34b56c95a94f5d5382677ba1e512288e163a2cd7b20a1bd2ad61; issue 01-persist-prepared-ref.md. Independent design Standards/Spec review: 0 hard blockers.

Persistent source /home/lee/financial-platform-isolated/refactor-worktrees/full-platform-20260918; deployment /home/lee/financial-platform-isolated. All three entry AGENTS files use the same accepted user rules and context capacity preference. No product edits at local workspace. No commit/push or true financial execution.

Accepted backend API/standard/discovery image remains dca460d790555fc211f145ceab9089afb0fbc64ccb5749d6662f1a700d0b7a23, frontend b8990adbbaedda8b6de1f4490dfbe2bece9e6583036cd8cdcd6b49396ab9e603. This stage has not changed running services. This turn's earlier independent runtime readback confirmed normal, API healthy, both Python workers running (no Docker Health field), active counts zero and existing historical markers unchanged. Refresh those facts before releasing; they are not permanent authorization/state evidence.

## Source implemented so far

The real ArExecution.script effect route bypasses the old implicit caller commit. A frozen prepared value is created from the task-owned exclusive fact. Independent same-Engine transactions append original prepared_process_refs plus ar_process_prepared_registered Audit atomically, then freshly take global/action locks and verify claim, binding, permissions/material, cancellation and post-lock PG clock before Popen. Only Popen/started is inside the second lock window; that read-only transaction rolls back before communicate/cleanup. Current fresh binding also calls original require_not_abandoned(workflow).

Last source hashes at 03:00 UTC (subsequent targeted slices may change them; re-read before edits):

- ar_process_evidence.py 98277808f4853e58dcfeb7aadcfe9478bd13945575434c1b8355851b0bd42ed9
- ar_execution_runner.py 4f64efaa857b5e427b04d6eaae028cb9c6129568184ab646af8e7bab8dcb21ae
- ar_execution_safety.py 6a52ea803ab14977b19e3721a41d290dde6d89588dca14fb51ae49c7c69551f7
- workflow_service.py 97846bdf34c30f33e5b6c899315f228976a842b77b8b911a466357b6c30acd21 (not modified in this stage yet)
- test_ar_process_anchor_postgres.py 68191b4df715864cd2a2f94eeff26a5a0ca80cef471492db679c027cea0bf626

AST and the three-file targeted diff check passed for the last source. This is not final Standards/Spec sign-off. The four existing effect names are unchanged; current actual spawn handlers are write_ledger, write_receipt_flow and complete_reconciliation. publish_reconciliation has no spawn and retains its outer publication transaction. API queues controlled tools, standard's workflow pool runs them, discovery does not claim these actions, Node Agent calls the API and waits. Updating the three Python services later covers this stage; no Node rebuild is required for this change.

## Real focused evidence achieved

The first real constructor/script/permissions/material/safety/lease seam failed as intended before Popen: another PostgreSQL Session saw original intent but zero prepared refs. One failed, no skips, 1.29s; no child launched. Then the same unchanged test passed in 1.28s, with actual benign no-op/Linux supervisor execution, another Session seeing the committed 8-field reference and matching 7-field Audit/revision before Popen, original binding/intent preserved and synthetic material bytes unchanged.

Two further single-case PG checks passed on the first candidate: a real server failure during the prepared Audit INSERT produced zero Popen and no partial ref/Audit/index revision change (1.18s); a real database COMMIT followed by injected lost response retained committed refs/Audit but still produced zero Popen (1.23s). These used actual isolated connections, not mocked guards.

The fresh-abandonment case then failed meaningfully: after anchor commit, another connection registered a recognized historical display marker, and the old candidate still attempted Popen. The OS boundary intercepted it, so no child ran. After adding the original fresh abandonment guard, the case passed in 1.24s with zero Popen and the original anchor/Audit intact. A legacy display marker was never used as full stop proof.

Each case was selected independently; no final combined class pass yet. Source changed between the first checks and the fresh-abandonment fix, so do not describe this as all tests passing on the final version. Test database/server/runtime data were synthetic tmpfs with network-none, no production DB/workbook mounts. All owned labels were verified zero after cleanup. Logs and diagnostic reports remain local .scratch/pi-construction-20260923.

Negative fixture results are retained: server DivisionByZero propagated directly rather than as the initially expected DBAPIError; fresh abandonment legitimately added another audit, so an overbroad all-Audit count was narrowed to the exact prepared-registration event and record. Those fixture failures were not product defects or hidden passed assertions.

## Immediate continuation

Regression agent is beginning the real PostgreSQL action-lock wait crossing a lease deadline. Implement/test one slice at a time. Still mandatory before F4.B delivery:

1. Sticky heartbeat loss: initialize once before heartbeat, mark loss even between scripts, remove per-script reset, reject the next spawn; current source has not implemented this yet.
2. Outer AR cancellation catch after independent gate release: rollback its own unfinished phase, freshly fence pinned claim with global/action locks and post-lock PG time, then write cancellation; stale owner must not overwrite a new attempt. Keep original already-locked publication transaction. Current workflow_service has not implemented this yet.
3. Caller uncommitted/flushed DML isolation and bounded lock failure; normal communicate/cleanup releases locks. Test actual PG connections and ownership rather than treating SQLite as concurrency proof.
4. Duplicate/conflicting refs, malformed refs, per-action cross-attempt 128/129 capacity and original historical binding preservation. Static review found script refs currently accept dot/dotdot/NUL; align with existing inspector script rules. SingletonThreadPool may reuse the same physical SQLite connection; explicitly reject unsupported shared pools rather than claiming independent isolation. Both are still pending.
5. Remaining spec failure/permission/material/attempt/Worker/binding/started-fact cases, final combined targeted tests plus applicable F4.A/F1/F2 checks, independent final two-axis source review, offline candidate build, guarded backend-only release and read-only browser acceptance. No production task mutation to create acceptance.

Root has only prepared local release helpers build_f4b_backend_20261008.py and prepare_f4b_deploy_20261008.py; neither build nor deployment has run. Builder recreates the accepted F2/F4.A overlay and four changed app files in one COPY on immutable cddc9 base, preserving all existing protected files/config/layer count. This is required because a prior additive-layer build hit mount options is too long. Final source hashes must be frozen and validated before use. Deployment helper is the existing backend-only notice/drain/full/health/rollback flow; the old frontend stays intact. Fresh active-task preflight is mandatory.

## Full goal still remaining

F4.B is partial/unreleased. Subsequent full F4 needs non-effect/independent-investigation anchoring, complete multi-attempt directory/Worker/external/business evidence and conditional administrator resolution. F5 real-file+DB publication crash matrix; F3 safe limited retry wiring; A25 maintenance fairness; F6 lifecycle fixture; G4 full Pi browser matrix; CW09 native metadata approvals; CW10 conditional DeerFlow renderer; CW11 final caller/crash/rollback/protected cleanup remain. No implicit pause/complete or scope reduction.


## Continuation update: lock time and caller ownership verified

Three more isolated cases passed independently on runner4f64/evidence982778/safety6a52; there are now seven individual-case checks, not a final combined-suite pass. A real second-transaction action-row wait was observed through pg_stat_activity; the holder released only after database clock crossed the deadline, and the fresh gate refused Popen (1.41s). Caller flushed FileRecord DML remained invisible to another Session while the anchor/Audit were visible; real no-op execution did not commit/rollback the caller, and the caller could still rollback its change (1.32s). Caller action-row lock plus a stricter actual 75ms lock_timeout produced PG55P03 and zero Popen; the caller's uncommitted changes/lock were not released by the gate (1.28s).

Last reported test hash6497dff840237fdd9e133a4880331e78d8969c2f134743a3595aa14510b11e65; further test slices remain in progress. Owned labels ecc0fe385dcc/ffcce9ff2c1c/1a62d5b4b906 were all cleaned to zero.

Immediate next slice is sticky heartbeat through real claim, real LeaseHeartbeat and original phase dispatch. Only the synthetic write_ledger phase handler may substitute two real no-op scripts; no workbook writer is executed. The isolated case may temporarily enable the execution setting while all real connectors/network remain disabled. Do not mock the claim/owner/material/safety/heartbeat guards, and do not portray the benign handler as business-write acceptance. Cancellation fencing, malformed/capacity refs, unsupported shared pools and all other unverified acceptance requirements are still mandatory before final review/build/deploy/browser. Overall goal remains active; no release, commit/push, true reconciliation or task mutation occurred.


## Continuation update: sticky loss and cancellation fencing

Ten isolated cases have now passed individually; final combined candidate validation and release are still pending. The real heartbeat wiring first failed because lease loss between scripts did not latch without an installed process callback. The minimal fix initializes the flag once at claim, marks every loss, and removes per-script reset. The unchanged test then passed in 1.34s: only the first benign no-op spawned, the next script rejected the known loss, and old running ownership was not overwritten.

The real outer cancellation race next failed because an old handler changed the action to cancelled after a new Worker/attempt had committed takeover. After sharing the existing no-commit fresh claim fence, it passed in 1.27s: the new owner, attempt, lease and progress remained authoritative, with original anchor/Audit preserved and zero spawn. A separate legitimate same-owner cancellation case passed in 1.29s: cancellation and finish state were saved, the lease cleared, and the registered anchor/Audit retained. These are actual PostgreSQL claim/gate/outer-handler tests, not workbook writer acceptance.

At those checks, source hashes were runner9dbffd901ab6aed804d24aca23a5eb090cfa57dc8009515b14c6028513182ff0, evidencefd8e4b12498b934fb493d563d31eb7c5f16263ec7f6719c61d8cd917760650f4, safety6a52ea803ab14977b19e3721a41d290dde6d89588dca14fb51ae49c7c69551f7 and serviced597462c0462b3c88ccaf1d82180fafac4dd3289d46a20e5a23a729cf50fdee2; the last test was ba1e89c8a1f3fa30d000706807a35d8d4e937db1634772035c2c6e0b038eac20. Re-read current files before editing; further slices are active. Owned labels 7112c62d951f/b1beaf9abea6/15c4a697d79d were verified zero after cleanup.

Independent ongoing review found two further fail-closed boundaries to test/fix within the approved matrix: heartbeat-triggered terminate/wait must not run while the spawn/started gate still holds database locks; fresh binding comparison must distinguish boolean True from the original integer material version 1. The malformed script grammar and SingletonThreadPool findings remain pending. Next slices cover these and the remaining ref/capacity/identity/process-failure/compatibility conditions. No final review sign-off, build, deployment, financial execution, commit or push has occurred. Live F4.A remains the accepted runtime and the entire construction goal stays active.


## Continuation update: strict identity and started-window cleanup

Fourteen cases have passed individually; this still is not a final combined candidate pass or deployment. The malformed historical ref case failed for dot and NUL basenames, then passed in 1.35s after aligning with the existing inspector grammar. A fresh boolean material version True previously compared equal to the original integer 1 and reached the intercepted Popen boundary; after type-sensitive field comparison it passed in 1.23s with original refs/binding/Audit intact and no new child.

The outer name-only metadata fault variant also failed meaningfully. Worker, attempt and lease were unchanged, but rollback/ORM refresh could erase the original action name. Pinning the name at the original execution entry, then checking the pinned name in the shared claim fence, passed in 1.26s with no stale cancellation outcome. This was an injected identity fault, not evidence that production claims normally rename actions.

The started-window loss callback case first failed in 1.59s: another real PG Session observed lock refusal before TERM/wait. After a minimal closure gate-active flag and lock-outside known-loss exception, it passed in 1.36s; each real TERM/wait was preceded by a successful independent lock probe, the benign child exited, sticky loss and original anchor remained. This explicitly injected the real heartbeat closure into the started window. Normal LeaseHeartbeat._touch first locks the action, and transient exceptions do not call loss, so this is not claimed as a natural production heartbeat race.

At these checks, runner001229cc1152feed7bee1fdab8342d9823257feb42bcf47a61031b7336b8aea3, evidence1ddb3a73bdcb7e5f5b5d4aa20b1a8811aa968c3e59fe8c7ecd8a88d460a4ed3b, safetycb9e24746b731d3933a24154147674eff5e17fbd400d536c8eeff372fd327353 and service637f9ea1226d562db50d4baae5945a62fb8462d5cd4b3b0ebe9d3c2c406a12f2 were current. Test52361645af64f5ec989032a452ead2728d067aca1caf13a17822573a82697a0e; later slices remain active, so re-read current hashes. Owned test resources were verified removed; evidence remains local.

Browser preflight is available without extension changes. The real 2026-08-30 historical batch page still shows zero registered attempts, two missing histories and insufficient full-stop proof, with no unsafe action button. Only the refresh-condition button exists; selected-date/history interactions produced zero workflow mutations. A historical console ERR_NETWORK_CHANGED was retained; a fresh maintenance GET returned 200. This is a pre-release baseline, not post-deployment acceptance and not a new zero-console claim.

Immediate remaining checks: unsupported SingletonThreadPool with real synthetic file SQLite (configuration/isolation rejection, not PG competition proof); cross-attempt 128/129 refs and duplicates/conflicts; remaining fresh claim/permissions/material changes, process/fact failures, successful transition and legacy compatibility; final combined focused runs and applicable F1/F2/F4.A regressions. Final independent two-axis review, offline build, guarded backend release, runtime/protected readback and fresh browser acceptance have not run. Full goal remains active; no real financial run, recovery, commit or push. All later F4/F5/F3/A25/F6/G4/CW09/CW10/CW11 work remains as listed above.


## 2026-10-08 04:10 UTC: F4.B deployed, browser acceptance pending

Frozen source: runner b8f24fa3a11945671ca4ec77014a819cdec52c64b3873c0a64f2943700d7fb47; evidence 1ddb3a73bdcb7e5f5b5d4aa20b1a8811aa968c3e59fe8c7ecd8a88d460a4ed3b; safety cb9e24746b731d3933a24154147674eff5e17fbd400d536c8eeff372fd327353; workflow service 637f9ea1226d562db50d4baae5945a62fb8462d5cd4b3b0ebe9d3c2c406a12f2. Frozen test 267f6c50976c74318a17832b7d94c4066c81585d1cf9c7fadf88698bf371e0ff.

The final focused class passed 21/21 in 9.39s, zero skip (20 real PostgreSQL scenarios and one file-SQLite shared-pool rejection; not 21 PG races). Applicable old regression passed 67/67, zero skip: 13 read-only attempt-history cases, 23 execution snapshot cases on real isolated PostgreSQL and 31 exact F1 abandonment/process guard cases. No F6 lifecycle blanket or full repository suite was run. Independent final Standards/Spec reviews have zero hard blockers. Static AST/diff and the bounded offline build passed. No real business writer, workbook or production reconciliation was tested.

Candidate and live API/worker-standard/worker-task-discovery image b93a027800f111b5f68fb3e7c7c6f56fbb2e4a46a2744b0ce01ed7ab6818e8ba. Build recreated the protected accepted overlay in one COPY on immutable cddc9 base, preserving Config and 456 layers. F1/F2/F4.A and independent balance.37 remain. Release used deployment.lock, pinned current runtime/source/config, notice, three consecutive zero samples, full maintenance, backend-only cutover, health and file-hash readback, then normal. Rollback files are releases/managed-20261008-040627-dcf96fed under the deployment root. No commit or push.

Independent live readback confirmed source matches on all three services, API healthy, two Python Workers running (no Docker Health field), normal and all five activity counts zero. All five nonselected service container IDs/images remained unchanged. The same Node Agent container restarted itself following the API disconnect; this was allowed by the release adapter and is not a replacement. Next image d177e8ea4802a55c8c49c181f694340cafc4fdcf1baf3a80a2d37024e0a11983/source_digest 3281996de2ca90daae60bbba45ccd9c1ceaf92d3dfdf9bb4a114661fada49756 is the separate R13 renderer release at 03:52 UTC, and was preserved. The old b899 image is historical, not current. That R13 release's own new renderer acceptance remains outside this F4.B check.

Three legacy markers remained historically visible and one still needs investigation; no context was mutated by readback. Neighboring kanban.service stayed active with MainPID817978 and /login HTTP200 before and after cutover. No real recovery, investigation/resolve POST, abandonment, permission change or financial retry/write occurred.

Browser navigation and a fresh batch-page snapshot succeeded after release. The next date/history interaction then failed because the Playwright MCP transport closed. Its console/tabs calls failed identically. Independent CUA inventory also failed to start codex app-server with Windows path-not-found (os error3). Thus date/history warning/button/GET and fresh-console acceptance are NOT complete. Root is diagnosing the local tool connection itself, without asking the user to enable an extension, resetting user browser data or treating the existing historical snapshot as acceptance. Do not begin the next implementation phase until real browser acceptance finishes.

All ephemeral helpers, synthetic test logs, comparisons and validation reports stay local; uploaded helper files and owner-labelled containers were hash-checked and precisely removed. The first snapshot regression fixture used the wrong synthetic DB name and failed the existing isolation guard; only the local harness DB name/URL was corrected, and the failed log is retained. No guard was weakened. Earlier temporary preflight generator quoting/brace errors were local helper failures and did not mutate the remote platform; those were fixed before the successful read-only preflight. Its source_matches=false means it deliberately checked the OLD live baseline, while the later deployed readback confirms true.

The whole construction objective remains active. Context budget follows capacity, saving a node and continuation before exhaustion with no numeric goal token budget. Remaining full F4 covers non-effect/independent investigation original anchoring, multi-attempt process/Worker/external/business proof and conditional administrator resolution; F5/F3/A25/F6/G4/CW09/CW10/CW11 remain as required. CW10 now has a parallel deployed optional renderer but no accepted full G4/performance/default-switch proof; do not revert it or call that whole scope complete.


## 2026-10-08 04:36 UTC: F4.B browser accepted; construction continues

Source, focused tests (21), applicable old regression (67), independent Standards/Spec review, build, backend deployment and independent runtime verification were completed at the preceding node. Fresh official Playwright MCP acceptance now also passed: owned ephemeral channel f4b-owned-browser-ea33faa64927, actual login/navigation, batch BAT-20260924-07ADB374, date 2026-08-30, recovery/history disclosures. The page reported registered0, missing2 and 13 action rows. The complete-stop-proof warning remained visible; the panel offered only refresh conditions, no recovery/resolve/abandon action. Actual execution GET200 and repeat GET200; maintenance GET200/normal; business mutations0, routine login1, observer errors0, fresh console errors0 (also confirmed by the official console tool). The owned browser was closed, no shared browser/CLI processes were closed.

Browser result and every completed official tool event were checked, not just the final narrative. Local evidence is .scratch/pi-construction-20260923/f4b-owned-browser-ea33faa64927/{acceptance.json,official-channel-events-redacted.log,run-metadata.json}. The first fresh channel d8026113b304 failed and its unknown/false acceptance log remains. Our request observer used a global URL constructor unavailable in the official tool VM; an event-time ReferenceError closed its transport. After replacing it with guarded String/regex parsing, the same fresh official route passed. No platform product change, global CLI/config change, browser reinstall or user-profile reset was used to fix that harness error. The old shared transport and separate CUA startup error are not claimed repaired.

F4.B is accepted within its frozen scope: durable immutable prepared refs before effect script spawn, fresh claim/material/permission/cancellation fencing, sticky lease loss and caller transaction isolation. Live backend remains b93a0278; protected parallel Next d177 and AR balance.37 remain. This does not persist all original terminal refs, cover non-effect/investigation callers, prove whole-workflow stop/no_effect/business success or authorize recovery. No production financial task, workbook write, recovery/investigation/resolve/abandon POST, commit or push occurred.

Next is F4.C-1: default-off, explicitly requested, original-attempt process evidence details in the existing execution GET and history UI. Formal spec/TDD must preserve original bindings and missing terminal refs, keep details separate from recovery authority and use bounded reads. Full F4 and F5/F3/A25/F6/G4/CW09/CW10/CW11 remain; whole construction goal is active. Save continuation by context capacity, without treating cumulative goal tokens as context usage or inventing a numeric limit.
