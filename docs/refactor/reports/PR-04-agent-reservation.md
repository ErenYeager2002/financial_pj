# PR-04 Agent call reservation boundary

2026-09-20: this slice deployed after the active task finished; runtime verified at 09:33 UTC. PR-04 and the full guide remain incomplete.

reserve_agent_call no longer skips the locked current-owner/action/lease check for legacy contexts. Legacy calls record a start authorization observation and preserve existing budget counters. Current contract calls record authorization and consume the budget in one transaction. Existing call sites perform only reads/argument preparation before this boundary. Audit failures prevent returning to the external call. Limits were not changed.

Ten new PostgreSQL tests cover current/legacy allowed, revoked, expired, cancelled and audit failure. Seven failed before the fix. After the fix, 93 approval-authorization plus 255 execution-authorization tests passed (348 total). Two read-only reviews found no definite regression. Static diff check and candidate/recovery migration/transaction checks passed. Both candidate and recovery match 453 backend/AR hashes.

Candidate 3d9e0cc0feb5 is built from live 462dac399323. Source and prior merged AR updates are preserved. Preflight found one active batch and one action, so no deployment was applied and no service restarted. Revalidate live immutable base and activity before applying. Current PR-04-image.json is the pending candidate; PR-04-image-before-agent-reservation.json is the prior live image.

Evidence: PR-04-agent-reservation-{red,approval-authorization,execution-authorization,candidate-check,recovery-check,preflight}.json.

Limits of evidence: reservation tests call the function directly and do not prove complete HTTP/model entry behavior. Contract classification still uses the context schema; fixed-contract anti-downgrade checks and full PR-04 matrix remain open. No real financial task, external model request or dashboard change was performed by this slice.

## HTTP boundary follow-up

Four actual FastAPI route tests passed for current/legacy model and tool requests. An independent PostgreSQL transaction disables the owner after initial authorization, during model configuration or declared-tool preparation. The route then returns 403 and the external model stream / queued tool sentinel is not called. Worker token authentication is overridden only in the test; no claim is made about token transport verification. The test uses synthetic model and tool declarations and no external request or financial data.

The latest approval-authorization run passed 97 tests; unchanged execution-authorization evidence remains 255 tests, 352 total. See PR-04-agent-reservation-http-tests.json. Runtime backend code and the prepared candidate are unchanged by this follow-up.

At 2026-09-20 09:28 UTC the same fetch_data action 0e148843-d03a-47df-b18b-57d3eee5e3fd remained live with renewed heartbeat 09:28:00 and lease 09:29:00. The platform reports one active batch/action. Deployment remains pending; no task interrupted, no new task/retry started, and no maintenance entered.

## Deployment completion

The observed fetch task succeeded. A fresh preflight found all activity counters zero and unchanged live base 462dac399323. Managed deployment of 3d9e0cc0feb5 succeeded, and API/standard Worker/discovery Worker each matched all 453 backend and AR source hashes, UID10001, schema f4b5c6d7e8f9, zero restarts, replay_only false. Internal and public modes are normal. See PR-04-agent-reservation-deployment.json and PR-04-agent-reservation-runtime-verified.json. Earlier pending statements above describe the wait before this final verification. No financial task was interrupted or retried.
