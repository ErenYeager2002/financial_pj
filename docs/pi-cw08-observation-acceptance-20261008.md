# CW08 observation scheduling acceptance — 2026-10-08

## Outcome and scope

This round is deployed and browser accepted. The user requested finishing this round and then pausing. The full construction objective remains incomplete; no next-stage implementation was started.

Only the session observation hook, the extracted observation scheduler and its tests changed. Observation is serial, coalesces wake-ups, uses a five-second hidden-page interval and cancels an old read when returning to the foreground. The fresh state gate keeps sending and model controls disabled until a current observation is available. Sending, controls, environment start/stop and business execution do not use the observation cancellation signal. No message replay was added.

## Verification and deployment

The targeted suite passed 80 tests, TypeScript passed, production build passed, and scoped static review found no remaining blocking issue. The initially reported slow in-flight read issue was fixed and re-reviewed. No broad/full unrelated test suite was claimed.

- Frontend: `sha256:cfd960509a9e013af1d24f35e5ed0cd9d49cf639a30fe54cbdf6b57aca9f0c10`.
- Build manifest: `8ca80c9201a8163e6f04df73af840af0898bcc72df28bdc94464ac8ebd3a3235`.
- Rollback: `/home/lee/financial-platform-isolated/releases/managed-20261007-224853-ed0cf650`.
- Independent readback: running image, manifest and checked source hashes match; Next healthy, maintenance normal, all five active business counters zero. Rechecked after browser cleanup.
- Source hashes: hook `0b19f107a39d56e87a9f8e52cb8e884312a4c728829124eeec64bd2fa861581e`, scheduler `3bbaf052e8f2a05475ab0ad6da6f143842c2b8c58187be2d090e9c4f2cf872f2`, tests `780452d6d9c877ba8275413cc6ccc4a5838880862e65b05169b8f0525fdeaca8`.

## Actual browser evidence and limits

The browser connection was recovered with the dedicated Playwright browser tool. The earlier browser-unavailable audit is superseded for this round. Acceptance used only the owned synthetic session `7089fbdc-6ca0-40e0-aabc-3775092e86d9`, with no financial tools, materials, grants or workbook writes.

1. Native tab switching in this automated browser kept document visibility visible. Therefore the hidden-page case used a controlled, reversible document visibility injection; it is not claimed as an operating-system background-tab test. Two hidden polls were observed, 5106 ms apart. Return issued the first fresh poll immediately. The only four other operations were read commands; no send/start/stop was issued by recovery.
2. A session-local browser route held an old observation response. Return canceled the old request (`net::ERR_ABORTED`), and a new poll appeared within 2 ms while the old response remained held. With the new poll held, send/model controls were disabled. Releasing the new poll restored controls and kept the unsent draft. Releasing the old response afterward did not regress controls. The test did not mutate server data or financial execution.
3. Thinking controls received actual successful Pi RPC responses and subsequent state responses. The selected model reported `reasoning=false`, so Pi retained `off`; this is not claimed as proof of a reasoning-capable model switching to low.
4. Actual UI navigation to Tool Center and browser Back stopped page observations while unmounted, preserved the draft, restored the AI page, and left the owned environment running. No start/stop or execution command was emitted during navigation. This validates an idle runtime surviving page navigation, not a new long-running financial execution test.
5. The synthetic text canary and its exact reply remained one user message and one assistant reply after navigation; no replay occurred. Browser console errors were zero.

## Cleanup and pause boundary

All visibility overrides, route interceptions and test listeners were removed. The extra test tab was closed, the original empty composer restored, and the owned runtime was closed through the UI and verified as closed/non-occupying. The other two environments were left unchanged. Exact uploaded helper cleanup was verified; temporary evidence remains local under `.scratch/pi-construction-20260923/`. Rollback files and necessary production data are retained.

Full G4, CW09/CW10 and final gates remain open. A separate read-only finance audit found an abandonment evidence-scope gap and ordinary Run first-100 starvation; these are recorded as later work, not fixed or released in this round. On resumption, inspect current source and active jobs again, prioritize the abandonment scope guard, and preserve independent AR changes. No commit, push, real reconciliation or workbook write was performed.
