# PR-05 transient heartbeat outage verification

2026-09-21. This slice changes synthetic tests and implementation records only. No application source, production configuration, financial material or dashboard resource changed.

Three PostgreSQL regression cases now execute the real LeaseHeartbeat loop, inject one connection-creation OperationalError, then recheck real database rows for a valid, expired or superseded Workflow attempt. Valid eligibility renews; expired and reassigned attempts leave their deadlines unchanged and set lease_lost. All cases preserve running state and never initiate financial execution, replay or process termination. This validates recovery after a simulated connection failure, not a physical network partition or indefinite outage behavior.

Command: python3 scripts/refactor/postgres_baseline.py --suite approval-authorization. Final exit 0, 111 tests passed in 59.04 seconds. First run: 110 passed, one new valid-case assertion failed because the shared fixture used a ten-minute lease while configured renewal is one minute. The new fixture now starts with ten seconds remaining; the renewal assertion was retained. No production implementation was changed to satisfy the fixture. JSON evidence: PR-05-heartbeat-outage-tests.json.

The actual leases.py SHA-256 is a7756b6a984a560f987520b8d2e721f2b04a93eee6679dbac64472553a4a950d in persistent source and API/standard Worker/task-discovery Worker. No restart is required for tests/docs. Static test diff check passed. The disposable PostgreSQL runner completed its owned-container cleanup.

I12/I13/I14 are the relevant boundaries. Remaining PR-05 requirements include structured lost-lease observation, bounded handling of continuing DB outage, common immutable risk/retry policy, reliable process outcome evidence, terminal fencing and waiting-user capacity. PR-04 remaining acceptance and PR-06 through PR-21 are not complete.

Next implementation: bind explicit raw risk declaration provenance to the fixed Skill snapshot and use one pure evaluate_retry_policy for automatic and manual retry. Do not treat normalized defaults, step defaults, an interrupted HTTP POST or lease expiry as proof of safe replay. Current scheduler and run_service still use divergent gates; this run did not alter them.
