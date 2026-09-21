# PR-04 Workflow authorization observations

2026-09-20: deployed and runtime verified; PR-04 overall remains incomplete.

Extracted shared record_authorization_observation from the existing ordinary Run implementation without changing its digest algorithm or commit ownership. workflow_owner_context now accepts explicit observe_phase/action; default calls remain read-only and preserve existing 403 semantics. AR execute_phase and script launch record start (write for the two workbook write actions), while publish records publish under the existing execution lock. Workflow/action/attempt identify the observation. Personal names, credentials and workbook content are absent from details.

The actual script boundary commits the observation before launching a child. Publication observation remains in the caller-owned publication transaction. The event proves authorization facts passed, not successful business execution or instantaneous cross-system revocation.

77 approval-authorization and 255 execution-authorization cases passed (332 total). New tests verify changed grant digest, revoked/disabled/moved owner rejection, caller rollback, actual script entry committing the event before child launch, and audit failure preventing launch. Two read-only reviews found no definite defect. Candidate/recovery migration and transaction checks passed. git diff --check passed. No actual financial task was run.

Concurrent release 1b99fb1fff3e changed eight AR files; normalized-byte comparison confirmed no independent source conflict and preserved all eight. Candidate e71f8f147022 deployed after zero active tasks. API/standard Worker/discovery Worker each matched 453 source hashes, revision f4b5c6d7e8f9, UID10001, restart count zero, normal mode. The recovery image is a distinct replay-only core, not full old-code restoration. Dashboard was untouched.

Evidence: PR-04-workflow-observation-{approval-authorization,execution-authorization,candidate-check,recovery-check,preflight,deployment,runtime-verified,live-diff}.json. PR-04-image-before-workflow-observation.json retains the previous image.

Remaining: workflow claim/other legacy and Pi entry observations are not covered by this slice; all-path phase matrix and restricted completion before script start remain open. No claim that PR-04 or the whole execution guide is complete.
