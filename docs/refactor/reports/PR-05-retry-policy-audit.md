# PR-05 retry policy audit — 2026-09-21

Read-only source audit while a real financial batch prevents the prepared Pi release. No retry policy has been changed or deployed by this audit.

Confirmed gaps against execution-guide section 6.7:

- scheduler._run_is_retryable defaults a missing risk.level to read_only; it accepts every adapter except rpa. Missing risk declarations and unknown adapters can therefore pass. A decoded JSON list or non-object risk value can raise an attribute error instead of denying retry.
- That automatic gate checks only adapter, risk.level and attempt_count. It does not check modifies_uploaded_files, current owner/file access, cancellation/manual-wait facts or uncertain side effects before recover_expired_jobs requeues the old execution.
- run_service.retry_status uses the current registry manifest and rejects modifies_uploaded_files, but does not share the automatic attempt/adapter policy or explicitly evaluate the immutable original risk declaration and uncertain execution facts. prepare_retry_request verifies input hashes and creates a new run with retry:<old-id> idempotency; these checks and semantics must be preserved.
- registry.RiskSpec defaults level and booleans. A future evaluator must distinguish a complete trusted execution snapshot from a malformed or incomplete raw historical declaration; revalidating a raw dict through defaults is not sufficient evidence.

Next implementation: derive typed retry facts from the immutable snapshot and current authorized/file-access checks, then implement the guide's pure evaluate_retry_policy(snapshot, execution_facts, reason). Both automatic and manual entry points must consume its conservative common decision. Explicit deny cases must include malformed/missing risk, unknown/unsafe adapter, material modification, uncertain side effects, exhausted attempt limit, cancelled/manual-wait status and revoked access. Preserve ordinary Run fencing, transactional event/step updates and manual input hash validation. Financial writes are never automatically replayed.

Still to investigate before implementation: safe-replay capability for each adapter, snapshot normalization provenance, step retryable/is_idempotent semantics, reliable process-exit evidence, and manual retry-chain attempt accounting. This audit does not infer that the differing branches already caused duplicate writes.


## Adapter and step evidence follow-up

- adapters.py registers only python, rpa and http. Python/RPA share SubprocessAdapter. Its normal completion calls process.wait(), and cancellation/timeout attempts to stop the concrete child. These are local control-flow facts; the generic RunRecord has no durable process-exit-confirmed field. Lease expiry alone cannot supply a persisted exit fact after a Worker crash.
- HttpAdapter always sends httpx.post. There is no adapter-level safe-replay capability or remote idempotency/receipt check in that method. A risk label alone does not establish that an interrupted POST can be repeated.
- step_runtime_service.py creates the generic execute step with retryable=True, is_idempotent=True, max_attempts=2 and risk_level=read_only for every standard definition. These generated defaults are not independent evidence of a Skill's replay safety. The common retry decision must not trust them without binding to actual immutable risk/capability declarations.
- modules/execution/run_snapshot.py binds a manifest digest and input/owner/adapter identity, and can recover an original snapshot only from a unique bound idempotency receipt. Keep that validation. RiskSpec defaults may already have been inserted during manifest normalization; inspect submission serialization provenance before treating a fully populated stored risk object as an explicit original declaration.

Additional regression cases needed: generic step flags true with a writing manifest; interrupted HTTP POST with no receipt; missing child-exit evidence after a lease timeout; normalized defaults originating from an omitted raw risk declaration; and a manual retry chain creating new Run IDs without resetting the allowed attempt budget. This follow-up is an implementation constraint audit, not an adapter behavior change.

## Snapshot provenance confirmed

Registry.snapshot serializes RegisteredSkill.public_dict(include_schema=True), not the raw tool.yaml declaration. Normalized RiskSpec defaults therefore cannot prove that the original manifest explicitly declared all safety properties. The next policy implementation must bind raw declaration provenance to the fixed Skill snapshot, or add a compatible versioned immutable contract; do not silently treat existing normalized defaults as complete explicit declarations.
