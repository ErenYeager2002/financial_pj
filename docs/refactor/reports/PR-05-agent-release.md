# PR-05 API and Agent paired deployment preparation

Status: deployment tooling implemented in the persistent Ubuntu worktree; application protocol is not yet changed or deployed. PR-05 remains incomplete.

The backend-schema command accepts exact local --agent-image and --rollback-agent-image digests together. The immutable Compose plan pins API, standard/discovery Workers and the selected Agent; other services and settings are preserved. Existing graceful drain and full-maintenance guards apply. The new Agent is started only after the expected API image is healthy. Rollback selects the corresponding backend and Agent pair.

A timed-out replacement is persisted as switch-requested and blocks automatic repetition or generic reopening. Explicit recover-schema performs read-only observation of the actual replacement identity, matching API image, health and restart stability before another controlled cutover. A recorded, already-exited failed candidate can be replaced during rollback; unrelated container identities remain rejected. Ordinary non-paired release behavior is retained.

Validation on 2026-09-21: 57 scoped deployment unit tests passed, including failed-candidate rollback, cross-process recovery, mixed-pair rejection, configuration drift, unhealthy API and replacement timeout. Static diff check passed. A read-only preflight using current immutable production images passed with normal maintenance mode and all active counts zero. Tests use synthetic containers and do not prove a real paired cutover, real financial execution or Pi attempt fencing.

Evidence: PR-05-agent-release-red.json, PR-05-agent-release-tests.json, PR-05-agent-release-preflight.json. No production image switch, financial task, commit or push occurred for this preparation. Next: review the remaining protocol paths, implement request attempt binding in API and Agent, build both images, and use this paired deployment with actual runtime readback.
