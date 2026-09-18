# Pi upstream capability parity

Status: implementation-in-progress

Baseline: https://github.com/earendil-works/pi/tree/e4c75a73222ae2c72abb5f5314fa35ee8effc508/packages/coding-agent
Package: @earendil-works/pi-coding-agent 0.85.1. User requested all capabilities from the official Pi harness; do not substitute the previous agent-core subset.

| Area | Required capability | Verified |
|---|---|---|
| Runtime | Official pi-coding-agent 0.85.1: interactive, print/JSON, RPC, SDK | Official package/terminal/RPC running; SDK session/tool invocation verified; SDK model and print/JSON acceptance pending |
| Tools | read/write/edit/bash; grep/find/ls; images and file references | Official SDK read/write/edit/bash/grep/find/ls verified; image read/preview/download and browser verified |
| Models | Provider catalogs, model switching, reasoning levels, custom models/providers, API key/OAuth | Platform model broker, switching and high reasoning verified; personal OAuth/custom provider pending |
| Sessions | JSONL persistence, resume/new/name, tree navigation, fork/clone, bookmarks, import/export | New/resume and active session tracking verified; tree/fork/export/import pending |
| Context | Manual/automatic compaction; original history retained | Pending |
| Messages | Steering, follow-up queue, abort, clear queue | Pending |
| Resources | AGENTS/CLAUDE/override, system prompts, automatic/manual Skill loading | Pending |
| Templates | Prompt templates and slash commands | Official get_commands, template expansion and extension invocation verified in chat; parameter variants pending |
| Extensions | Custom tools/commands/events/providers/UI; installation and reload | Tools, synthetic registered command and four dialog types verified; notifications/widgets/providers/reload acceptance pending |
| Packages | npm/git package install/remove/update/config; pinned versions | Pending |
| UI | Themes, shortcuts, tool/thinking folding, token/cost/context status, editor/file completion | Pending |
| Trust | Per-user project trust, resource isolation, explicit sharing | Owner and department isolation checks passed; project-trust UX acceptance pending |
| Platform | Durable workspace, browser automation, long jobs, dependency persistence, upload/download, audited access | Durable jobs/browser/files/native Skill conversations/read-only business query verified; business execution/private credentials pending |

Extension support does not mean preinstalling every third-party package. Subagents/MCP/plan mode are extension capabilities rather than built-in defaults. Permit extension installation within user runtime. External sharing remains an explicit user action; never share finance sessions automatically. Terminal-specific interactions need either their original interactive interface or equivalent web controls; RPC alone must not be presented as full interactive parity.

Observed: isolated runtime image built, pi --version = 0.85.1, pi --help succeeds. No production service switched.

2026-09-17 incremental evidence (full parity still pending): owner-scoped manager and authenticated API deployed; isolated same-session-ID cross-owner file check and workspace/HOME persistence after container recreation passed. API unauthenticated/forged-owner/cross-owner/cross-department/path-traversal checks passed. Official RPC empty new session survives restart; synthetic bash remains running after 123 seconds, then abort_bash cancels it; PTY works after switching from RPC. Runtime image 0.85.1-session-v2-20260917 matches bridge source. These checks do not prove model calls, networking, browser support, web refresh/resume, extension UX or full Pi capability parity. Web forwarding routes are source-only; user-facing UI remains pending.

2026-09-17 additional deployed evidence: v4 official runtime tracks session_start in both terminal and RPC; /new, terminal restart and return to RPC preserve the selected official session. Dedicated public egress permits HTTPS/npm/pip and Playwright Chromium; link-local targets are denied. Per-owner Docker networks use isolated gateway mode; host bridge has no IPv4 address. Manager restart preserved a running synthetic command and instance ID. Explicit stop works with a missing control socket and stops the owned container. Web /dashboard/pi is deployed; production build and TypeScript passed. Authenticated HTTP checks passed for page/session create/start/poll/page reload/stop, and unauthenticated routes return 401. Browser visual/interactive QA remains pending because the browser connector failed to initialize.

Resource isolation: Pi-only systemd slice MemoryHigh 4 GiB / MemoryMax 6 GiB / CPUWeight 50; max 12 environments globally and 4 per owner; 512 tasks per container. Persistent HOME/workspaces are now on a separate preallocated 32 GiB ext4 loop filesystem, required before the manager starts. Existing files were copied with ownership preserved and matching SHA-256 hashes. These boundaries apply to the new Pi runtime, not financial Workers. No financial tasks were rerun.

Still pending: platform model broker and live model/tool validation, private business system access, model-callable browser tools, web file transfer, integration with existing Skill conversations, complete upstream capability acceptance and interactive browser QA. Installing the official package and serving its terminal does not prove these items complete.


## 2026-09-17 platform model integration deployed

Official Pi now receives an owner-scoped model credential generated by the authenticated platform API. The private broker resolves current account status, department, password epoch and model ACL on every request. Provider API keys remain in the trusted broker; Pi receives no shared provider key. The broker exposes only /v1/chat/completions over a private Unix socket, has no published port, runs as UID 10001 with a read-only root, and mounts only its socket directory, read-only token index and read-only credential key. API/broker source hashes were checked against running containers.

The full native terminal keeps personal providers and gains financial-platform entries for the department default and allowed connections. Current acceptance observed 15 entries (including the default alias), native model switching and high thinking. Known model metadata comes from the installed upstream provider catalogs. Native thinking/sampling choices are preserved instead of inheriting the legacy assistant's thinking-disabled defaults. Go reasoning fields are normalized for multi-turn replay. Node's HTTP CONNECT proxy behavior was tested and fixed for the dedicated model endpoint; authorization remains mandatory.

Validation: isolated token tests rejected unknown tokens, disabled users, changed departments, forced-password-change accounts and changed password epochs. Model binding discarded client URL/key fields. Fragmented SSE normalization and preservation of personal model configuration passed. A real platform-model conversation successfully called write then read, with file content verified on persistent storage. Persisted official history proves high-level thinking output in that tool loop. A later trivial arithmetic reply contained no separate thinking block; the initial assertion that every high-thinking reply must contain one was invalid, and the stronger history evidence was used instead. No financial files or real finance workflows were used. Synthetic session files were archived locally, SHA-256 verified, then removed remotely; formal settings and audit records remain.

Deployed images: backend/broker financial-platform-isolated-backend:pi-model-20260917; runtime financial-platform-isolated-pi-runtime:0.85.1-session-v5-20260917; egress financial-platform-isolated-pi-egress:model-20260917; web financial-platform-isolated-next:pi-workspace-model-20260917. Web production build and TypeScript passed; API healthy and unauthenticated frontend/model routes reject requests. Rollback: releases/pi-model-20260917-rollback.

Full goal remains incomplete. Remaining required work includes uploaded read-only originals and output downloads, persistent model-callable browser actions, explicit asynchronous job IDs/status/output/cancel, business-origin/credential integration, existing Skill conversation integration, original Pi packages/Skills/templates/extensions/context/queue/session-tree/export acceptance, personal OAuth/custom-provider acceptance, and browser interactive QA. This model milestone does not replace those original requirements.


## 2026-09-17 durable Pi jobs deployed

Runtime v6 adds the official platform_job extension with start/list/poll/cancel. Each command immediately receives job_id. Supervisors run independently of the Pi conversation process; state/output live in the session workspace. Poll reports observation timeout separately from execution state. Container interruption is marked interrupted on recovery and never auto-restarts the command. Output retains byte cursors and complete UTF-8 boundaries. Captured output is capped at 64 MiB with output_truncated explicitly reported; larger artifacts should be saved as files. Concurrent jobs are bounded at 16 per environment.

Review fixes: Linux child subreaper and post-pidfd-open ownership checks cover setsid descendants; cancellation/cleanup failure is not marked successful. Shared state updates use interprocess file locks. Request bytes are read without truncating permitted Unicode commands. Tests passed for UTF-8 split boundaries, detached child cancellation, official extension loading, job survival after Pi exit, a still-running job after 123 seconds, observation timeout without execution failure, and terminal cancellation state. A real platform model invoked platform_job start and poll successfully. An actual container stop/restart retained the job/output, marked it interrupted, and verified its execution counter remained exactly one. Final deployed source hashes matched pi_jobs.py, pi_jobs_extension.ts and pi_runtime_server.py. Synthetic test artifacts were fetched, SHA-256 checked and removed remotely; formal audit remains.

Image: financial-platform-isolated-pi-runtime:0.85.1-session-v6-20260917. Manager service active; deployment updated only the Pi service/image selection, not financial services. Rollback: releases/pi-jobs-20260917-rollback. Full goal still requires file transfer/read-only inputs, persistent browser actions, business credentials, existing Skill conversation integration and remaining upstream capability acceptance; do not claim completion from this milestone.


## 2026-09-17 persistent browser tools deployed

Runtime v7 adds platform_browser: navigate, snapshot, click, fill, press, screenshot, list/create/close tabs and close browser. Chromium runs in the user's existing isolated container with the dedicated public proxy; local loopback is the user's own container. A bridge-owned event loop retains tabs/profile across Pi agent process restarts. Element refs are scoped to the tab and refreshed with snapshots. Screenshots return image content and a real PNG in /workspace/outputs. Browser content is explicitly treated as untrusted data in the tool description. Timeout errors do not automatically repeat actions.

Review/test fixes: browser CLI honors its 45-second timeout versus the 40-second service bound; session cookies are restored from atomic storage snapshots; persistent profile retains localStorage; unexpected closed contexts and failed launches are cleaned up before explicit reuse; explicit environment stop flushes browser state before stopping the container. No automatic page actions are replayed after recovery.

Validated in an isolated local test page: visible text, current refs, Unicode fill, click, PNG screenshot, multiple tabs, cookies and localStorage across browser close/reopen, recovery after unexpected context close, and official extension loading. A real platform model used write plus browser navigate/fill/click on a synthetic local form; direct browser readback confirmed PI_BROWSER_OK. Public HTTPS opened Example Domain. The same test page and browser tab survived a Pi agent restart and Pi manager service restart. Deployed pi_browser.py, pi_browser_extension.ts, pi_runtime_server.py and pi_jobs.py hashes matched persistent source. Test session artifacts and screenshot were archived locally, SHA-256 verified, and remote synthetic state removed; formal audit remains.

Image: financial-platform-isolated-pi-runtime:0.85.1-session-v7-20260917. Rollback: releases/pi-browser-20260917-rollback. Full objective remains incomplete: file upload/download and read-only inputs, business credentials/origins, existing Skill conversation integration, and the remaining official Pi capability acceptance including interactive web QA still require work. Browser success does not prove those requirements.




Runtime v8 mounts uploaded originals read-only under /inputs/<upload UUID>/<filename>; official Pi receives file-location guidance. The authenticated web panel supports multi-file chunk uploads, directory browsing and streaming downloads after environment stop. Uploaded names are preserved in separate UUID folders. Manager opens paths by directory descriptors with O_NOFOLLOW and only regular files/directories; downloads verify file identity/version on each chunk and never buffer the entire file. Owner/session catalog checks remain server-side.

Review fixes: explicitly chmod upload directories to 0755 under manager UMask 0077; prevent stale directory entries generating links for a new path; empty listings return next_offset null. Validation passed for UID10001 original reads and denied writes, traversal/symlink rejection, >1MiB upload/download SHA and byte equality, download after stop, nonexistent session and unauthenticated rejection. API source hashes match runtime; actual v8 container mount is read-only. Web production build/TypeScript passed, API healthy, manager active. Synthetic artifacts were archived locally with per-file SHA verification and removed remotely. No real financial task was run.

Images: backend and next pi-files-20260917; Pi runtime 0.85.1-session-v8-20260917. Rollback: releases/pi-files-20260917-rollback. Browser visual QA, business origins/credential integration, existing Skill conversation integration and remaining official Pi capability acceptance remain incomplete.


## 2026-09-17 browser UI acceptance and terminal correction

The Chrome connector recovered. Actual authenticated browser actions passed: create session, start terminal, upload a synthetic file using the picker, ask the platform model to read/copy it, view the output folder and trigger a real download after stopping the environment. Host readback verified original and copy SHA256 equality.

Browser QA uncovered an intrinsic-height feedback loop: terminal grew to 20424px/1200 rows and resize requests were rejected. The terminal now uses a definite viewport-based height bounded at 360..900px instead of growing with xterm contents. Measured 554px/32 rows remained stable after native /hotkeys and page reload. No alert remained. Stop now suppresses queued input/resize requests and their stale errors. Runtime v9 preinstalls fd-find plus fd alias, removing startup auto-download timeout. User-terminal stop, version upgrade and original session-history restore passed.

Current images: next pi-files-v3-20260917; API pi-files-20260917; Pi 0.85.1-session-v9-20260917. Production build/TypeScript passed. Runtime source hash matched. Synthetic session, inputs, outputs and official history were archived locally, per-file SHA verified, then removed; formal audit remains. No financial jobs were run.

Remaining goal: private business origin/credential integration, existing native Skill conversation integration, and official capability acceptance for packages/Skills/templates/extensions/custom-provider/OAuth/session-tree/export/compaction/queues. Existing native_skill_service.execute_command still uses the old per-command executor; it must not be reported as using the full Pi runtime yet.


## 2026-09-17 Conversational Agent in AI assistant deployed

Existing /dashboard/ai-chat and installed Skill run pages now use PiChat with conversation messages, tool result cards, file upload/download, model/thinking selection, official abort/steer/follow-up and refresh recovery. Terminal remains auxiliary; legacy business conversations remain available through legacy=1. Production build and TypeScript passed. Initial HTTP-only crypto.randomUUID error was rolled back immediately and corrected using existing createClientId fallback. Frontend pi-chat-v3-20260917 is live; API remains pi-skills-20260917 and runtime target v10.

Actual browser acceptance passed synthetic file write/read exactly once, recovered conversation/tool history after reconnection, model options, and interrupted reply. Composer was verified within viewport after height correction. Synthetic session 0653ba96-969d-4423-89ff-aee426e894a3 was stopped and archived locally (8 files, per-file hashes verified, archive SHA256 80a7ad8946197c27d3ed511efe1fa8c041388830e8a3d89f10de12f12e12d69a), then exact test container/session/catalog/history removed. Existing real Pi environment was preserved. No financial task was run.

Full goal is not complete: authenticated business tool/credential bridge, background job UI controls, extension UI requests, images, and remaining upstream capability acceptance are still pending. Aborting a model reply does not cancel background jobs; explicit environment stop does.


## 2026-09-17 Chat background job controls deployed

Added PiJobs panel in AI assistant/native Skill conversations: list current jobs, incremental bounded log view and cancel directly without model calls. API and manager only accept list/poll/cancel on this surface; polling a stopped environment never starts it. Owner cancellation remains available after Skill revocation; session ownership is always checked. List/log/cancel errors are separate so successful polling cannot hide cancellation failures. Scope limit: stopped environment history is accessible as workspace files under .pi/jobs, not directly in the job panel yet.

Production build/TypeScript and synthetic manager list/log/cancel/no-start checks passed. Browser acceptance created c8ff499e-c7d8-4d39-863b-cb7b657f511d, displayed running job/log CHAT_JOB_LOG, cancelled it through UI and observed cancelled exit -15. Environment explicitly stopped. Tests archived locally (12 files, SHA256 a6e4f5e795b4782f601a8d138b693c4e4501981a4bb24c9075a1552701e9ed56), verified and removed exact synthetic container/session/catalog/history paths. Standards and spec reviews found shared error clearing and revoked cancellation gaps; both fixed.

Frontend image pi-chat-jobs-20260917. Another concurrent flow-prefill deployment changed API during acceptance; final healthy API sha256:c11447b0aa6f1eaa52bd4025d4fe2e750e79e09a19abd279c67e05110c93c28b retains exact current pi_runtime_service.py and routers/pi_runtime.py hashes. Its deployment journal reports succeeded/normal. Existing real Pi container ID/start time unchanged. No finance operation executed and no Worker restarted by this change. Full Pi parity goal remains incomplete; business bridge/credentials, extension UI, session features and remaining upstream acceptance pending.


## 2026-09-17 Official extension dialogs in chat

PiChat now displays official confirm/select/input/editor requests with explicit responses/cancellation. Bridge owns a pending-dialog snapshot so refresh does not reconstruct approvals from historical events. Typed confirmations and offered selection values are validated; expired or completed IDs are rejected. Review caught timeout=0 semantics (official means no timeout) and AbortSignal cancellation not reported by upstream. Both fixed. A pinned fail-closed build patch instruments dialog cleanup in official dist/modes/rpc/rpc-mode.js AND actual dist/bundle chunk, emitting platform_extension_ui_closed without altering approval semantics. Source-only patch was insufficient because Pi CLI runs bundled code; actual bundled runtime was tested.

Real official Pi checks passed four dialog types, zero timeout, pending snapshot and AbortSignal cleanup. Browser acceptance in isolated session 95b5b35f-7de0-4151-bd69-d49b00da25f2 passed refresh restoration, explicit reject, selection, text and multiline editor responses, and cancellation disappearance. File readback exactly matched submitted values. Synthetic extension was guarded by exact session ID and removed after archive verification. All synthetic sessions/containers/catalog/history and test extension files archived locally (9 files; SHA256 60aa333a4977f843ecc9ca543b7456d95c7fea703e1bd878f1deac14854b06b8), then removed. No model/financial task was called by the dialog acceptance.

Deployment: frontend pi-dialogs-20260917; manager target runtime 0.85.1-session-v12-20260917. Production build/TypeScript passed. Existing user Pi environment remains on v9 with unchanged ID/start; no active environment was upgraded or stopped. New environments use v12. API/Workers not updated by this slice. Full parity still incomplete.

Business integration investigation: old agent-server.ts hosts platform_information, authorized Skills/status and controlled AR prepare/start; auth is server login context and material/execution authorization is in assistant_workflow_service.py. New official runtime must call a separately scoped authenticated business bridge, not reuse model-only broker credentials as platform-wide credentials. Keep existing legacy business conversation entry until migration is implemented. Additional pending: dialog notification/status/widget/editor-text handling, private credential fetch, full upstream acceptance. Project-local extensions are trust-gated; HOME extensions load normally; do not bypass project trust globally.


## 2026-09-17 Session-scoped platform query tool deployed

Official Pi now loads query_platform for live authorized task lists, published tools/installed Skills, and AR material/credential readiness. Existing business services supply values; the bridge does not start/retry financial tasks or return raw credentials. A distinct per-session token is bound to current account, department, password epoch, owner and session catalog/Skill authorization. Model credentials are not accepted on the business route. Agent containers receive only delegated session credentials, not database/provider/financial-service credentials.

Validation found the model-only broker omitted FINANCIAL_NETWORK_POLICY_MODE, which excluded both AR manifests under strict validation. Broker now inherits the platform internal policy and has minimal read-only catalog/native installation/material mounts. No Pi egress allowlist or Worker policy was broadened. Live tasks, skills and material service queries passed; 13 published tools and 18 installed Skills were observed. Ten synthetic rejection cases covered unknown token, wrong session, disabled account, mandatory password change, department change, password epoch, token purpose, owner mismatch, revoked session/Skill gate and rotated old token. Dispatch rejects unknown resources, owner injection and invalid pagination.

Actual new v13 session called query_platform twice through the platform model; both tool executions returned isError=false and the assistant reported catalog/material results. API is healthy. Source hashes match both API and broker; runtime image server/client/extension hashes match. Existing real Pi container 169c4853b933 retains its 2026-09-17T05:03:00 start. No financial task ran; no financial file was modified; Workers and frontend were not restarted. Synthetic session b23e794d-9467-4f42-9cdf-dd23ae9be046 was stopped, archived locally (7 files, SHA256 23edc1c61c8292c0590da59b2123022021743ea3c4c82520f73f38670992c39a), verified and removed with its delegated credential. Audit retained.

Deployed API/broker image financial-platform-isolated-backend:pi-business-20260917; manager target financial-platform-isolated-pi-runtime:0.85.1-session-v13-20260917. Persistent broker compose includes read-only mounts and 120-second graceful stop. Rollback: releases/pi-business-20260917-rollback. Existing running older environments were preserved and need an explicit stop/start before receiving the new runtime.

Full Agent goal remains incomplete. Financial execution authorization bridging and private business credential fetch still require implementation; preserve original legacy business conversations. Remaining upstream capability/UI acceptance includes packages/extensions beyond dialogs, session tree/export, templates, providers/OAuth, image presentation and usage/context reporting. Do not claim full parity from the read-only bridge milestone.


## 2026-09-17 Original chat shell restored and inline images deployed

User explicitly required the original business chat window dimensions and no compression by auxiliary panels. PiChat now reuses AssistantShell, places session controls in its header, moves file/job panels to a modal side drawer, and moves legacy links/history below the chat. Composer cannot flex-shrink; textarea remains 96px minimum and bounded scrolling. Message area uses min-height:0 to avoid clipping composer on short/narrow screens; error notices are height-bounded. Extension dialogs float rather than consuming transcript height.

Desktop live browser measurement (1920x855): original legacy shell 679px tall; new Pi shell also 679px, transcript 415px and textarea 96px. Opening drawer and expanding both files/jobs leaves transcript/textarea heights unchanged. At 375x667 the textarea remains 96px and entirely inside shell (narrow transcript 90.66px; full desktop transcript size is not promised on small screens). Production build and TypeScript passed. Both review tracks identified the initial transcript min-height clipping risk; corrected before deployment.

Official image blocks from user/assistant/tool results now render raster data inline with enlarged preview and download. Preview failures retain download; replacement data resets error state. Unsupported preview formats provide binary download. Actual Pi created/read a synthetic 320x180 PNG; browser showed blue rectangle/green circle in modal after refresh. Browser download event hook timed out, but downloaded file was found at the exact expected filename and its SHA256 matched the generated source: f62a2bf171853267a37786a5387d7c2527b0c0e69a592d2e1f5b3c10593e8ee0. Test image archived locally. Default tested model declared no vision support; rendering an image does not prove model vision capability.

Frontend image pi-chat-layout-v2-20260917. Only frontend was updated by this slice. A concurrent separate API/Worker rollout briefly enabled maintenance during browser QA; page subsequently recovered. Existing real Pi container unchanged. Synthetic session 964b2fde-80e6-4b57-ac05-e654d8c54b71, files/history/catalog/delegated credentials archived locally (8 files, archive SHA256 4b87002d30c7c6257ab3ff2179be82eecf7afeed2a35a2aecf6a35024414f1a2), verified and removed. Audit retained. Rollbacks: releases/pi-images-20260917-rollback and releases/pi-chat-layout-20260917-rollback. Full Agent goal remains incomplete; business execution/credentials and remaining official capability acceptance still pending.


## 2026-09-17 Official command discovery in chat

PiChat now requests official get_commands and offers a slash-command chooser for loaded Skills, prompt templates and extension commands. Typing / filters the list; choosing only fills the draft. Execution remains an explicit send. Recognized extension commands always use prompt, including while a reply is running, per pinned upstream RPC docs; Skill/template input continues through official prompt/steer/follow_up expansion. Built-in TUI commands are not fabricated in the list and remain available in the auxiliary terminal.

Review fixed raw-draft acknowledgement mismatch (selected command includes trailing space) and clipping of an absolutely positioned list by AssistantShell. Chooser now uses a bounded fixed portal without reducing chat/composer height. Browser verified exact no-execution-before-send, official extension command wrote only synthetic COMMAND_OK after send, draft cleared, and official prompt template expanded to an actual model reply TEMPLATE_OK. Official catalog returned 20 commands in this synthetic environment (includes test command/template). At 375x600 the popup was entirely within viewport, top86/bottom420/height334, textarea remained96px. Production build and TypeScript passed. No financial task was executed.

Frontend pi-commands-v2-20260917 deployed; rollback releases/pi-commands-20260917-rollback. API/Workers/runtime not changed by this slice; existing real Pi container unchanged. Synthetic e638a34b-dad9-475f-b5e9-2274f14967c6 and temporary HOME extension/template archived locally, all 10 member hashes verified, archive SHA256 075d9a7716964c069b2ebfa1df208cfae5f2e4cf84d308af3416f799571be19d, then exact synthetic files/container/catalog/credentials removed. Audit retained.

New confirmed pending defect: PiChat currently treats agent_end as settled although official docs distinguish agent_settled after retries/compaction/queued continuations. A client-only activeCycle patch was rejected and reverted because missing events or same-bridge process restart could leave permanent busy state. Next fix must expose an authoritative bridge snapshot keyed by process generation/instance and handle event gaps; do not claim that lifecycle defect fixed. Full Agent parity remains incomplete: business execution/credential bridge, lifecycle recovery, session tree/export and remaining upstream acceptance.


## 2026-09-17 Authoritative activity recovery and result-only chat deployed

Supersedes the preceding pending agent_end defect. Runtime v14 maintains an activity snapshot independently of the bounded event buffer. Official agent_settled clears the active cycle; retry/compaction phases remain observable. Poll includes process generation and instance identity; stale reader output from replaced processes is ignored. PiChat uses the authoritative snapshot and rehydrates history on generation changes, with compatibility for existing older runtimes.

Targeted regression checks covered event-buffer gaps, retries, compaction, settled state, process exit and stale-process events. Real official model acceptance executed only synthetic sleep commands. Browser refresh during execution retained busy state, natural completion restored idle, and a same-bridge process restart to generation 2 restored both ACTIVITY_OK and SECOND_OK history without stale busy state. This does not claim live provider retry or compaction acceptance. Both code review tracks completed without unresolved blockers.

At the user request, thinking blocks are no longer rendered in chat; response text, tool results and required confirmations remain. Production build and TypeScript passed. Browser readback after deployment showed both results with no thinking section. Frontend pi-result-only-20260917 is running. Runtime v14 image hashes match persistent pi_runtime_server.py and pi_activity.py. The preexisting v9 user environment retains its exact container ID and start time; its behavior is not claimed upgraded. API and financial Workers were not restarted by these slices.

Synthetic session 411b345d-1629-49d4-ba34-2fb2ea4e60eb was explicitly stopped, archived locally (7 files, each SHA256 checked, archive SHA256 816409ac8539de53c9429cdb11f6cc144b99ec3af12c3a83621d9f4eb61a4aee), then its exact container/session/history/catalog/delegated credentials removed. Formal audit retained. No financial task was executed. Rollbacks: releases/pi-activity-20260917-rollback and releases/pi-result-only-20260917-rollback.

Full Agent parity remains incomplete. Required follow-up includes business execution authorization and private credential access, packages and providers/OAuth, SDK/print modes, session-tree/fork/export/import, queue/compaction and remaining extension UI acceptance.


## 2026-09-17 Official SDK file tools and fd correction

Actual SDK createAgentSession in the deployed v14 image loaded all seven selected tools, but official find failed because distro fd rejected --no-require-git. Runtime v15 installs the official sharkdp/fd 10.3.0 Linux x64 musl binary. Persistent deployment/vendor records the release URL, archive SHA256 and binary SHA256, and preserves both upstream licenses. Docker build verifies the fixed binary hash and required flag, then restores UID10001.

Actual official SDK executions in v15 passed write/read/edit (including unified patch), grep/find/ls/bash. File content was checked after editing; find also respected .gitignore outside a Git repository. Tests ran with no network and tmpfs-only synthetic files, with containers removed at exit. These prove SDK construction/tool invocation, not SDK model inference or print/JSON mode; those remain pending. Both review tracks found no concrete blocker.

Manager default deployed to financial-platform-isolated-pi-runtime:0.85.1-session-v15-20260917; systemd is active and effective environment selects v15. Final image returns fd 10.3.0. Existing real user container ID/start time unchanged. No API/frontend/Worker restart, finance operation or user-session restart. Existing active older runtimes retain their old dependencies until explicitly stopped and started. Rollback: releases/pi-tools-20260917-rollback. Full Agent parity remains incomplete.


## 2026-09-17 Session usage drawer deployed

PiChat requests official get_session_stats on hydration, settled replies, successful manual compaction and model changes, plus manual refresh. PiSessionStats renders messages/tools/input/output/cache/total tokens, estimated USD cost and current context usage in the existing modal drawer. Null, absent and non-finite values remain unavailable rather than fabricated zero. Generation changes discard stale statistics. Thinking output remains hidden and chat dimensions unchanged.

Production build/TypeScript and both reviews passed after correcting missing compaction/model-change refresh. Actual browser acceptance: empty session correctly showed zeros; a real synthetic STATS_OK reply automatically updated messages=2, input=5577, output=27, total=5604, context=5604/1000000 and estimated cost=$0.0012. This validates usage display, not session tree/import/export or compaction execution itself. Frontend pi-session-stats-20260917 running; runtime target v15 unchanged. No Worker/API updates or financial operation.

Synthetic 07d9a6e6-a885-43c3-bfef-0ae1141e1b91 was stopped, archived locally with all 7 file hashes verified (archive SHA256 c1bcf8321dc9bead42b2f51e930df44d072166f4e6502e52ce77281f4d6304b6), then exact container/session/history/catalog/delegated credentials removed; audits retained. Rollback releases/pi-session-stats-20260917-rollback. Full Agent goal remains incomplete; official RPC has read-only get_tree but no navigate_tree/import command, so remaining session controls need an official extension or SDK-backed integration rather than invented RPC messages.


## 2026-09-17 Pi permissions, shared memory and independent entry points

User authorized writable isolated workspace/Skill drafts, user dependency installation, scripts/network and human-confirmed publication; did not authorize host root/Docker/shared provider secrets. User clarified AI assistant and Pi workspace must share conversation memory while retaining independent transcripts and simultaneous execution.

Implemented persisted channel on session creation, disjoint UI lists and separate session processes. Legacy assistant route/history UI and More dropdown removed; stop/compaction remain in the existing drawer so an exited Pi process can still release its container/background jobs. Existing records without channel remain in assistant; new workspace records are explicitly workspace. No original history deleted.

New owner+department /context bind mount shares durable SQLite memory and versioned Skill drafts. shared_memory recalls/searches/remembers task summaries, with transactional concurrent writes and credential-pattern rejection. Model prompt asks for concise durable summaries; complete transcripts and thinking are not automatically copied. The two entries keep independent JSONL histories. This is summary memory, not verbatim context synchronization.

Skill draft prepare copies authorized mounted packages to /context/skill-drafts/name/base-revision using flock and atomic staging; older edits remain when the base changes. Native Skill proposals snapshot immutable ZIP bytes, validate SKILL.md and Python syntax, show text and executable permission diffs and require the expected SHA256. Pi's delegated broker can submit candidates but has no approve route. Web-authenticated Skill administrators approve candidates in their department; normal users cannot publish. Publication creates a content-addressed native package revision and atomically updates installation metadata, leaving running snapshots and old versions intact. Runtime checks are not business acceptance; workflow tool rollout paths are not replaced by native Skill publication.

Validation: official extension loaded both tools; concurrent memory and draft prepare tests passed; new-base draft preserved old edits. Isolated backend tests passed employee proposal, department admin approval, cross-department denial, hash binding, immutable old package and idempotent publication. Production web build/TypeScript and two-axis reviews completed; findings around stop, department approval, atomic draft preparation, rebase and permission diffs corrected.

Live authenticated synthetic sessions ran simultaneously in RPC assistant and terminal workspace. Assistant stored MEMORY-BLUE-917 and workspace retrieved it using shared_memory and replied with it, without reading the other JSONL. Actual model prepared project-detail-to-ledger draft, appended only a synthetic HTML comment, and submitted candidate 3da04407-f73c-479d-a677-b55677b4f2ad. Browser showed exact diff and confirmation control; no production Skill was published. No financial script/task ran. All synthetic session/history/catalog/tokens/draft/candidate and only their memory rows were archived locally (22 members, per-member hashes verified, SHA256 3b0844d4fb6e66da63103198b6fba8c9aac44f531e0f60d5031a10e0a0de410b), then exact remote data removed. Audit retained.

Deployed API/broker/next pi-context-20260917; manager target runtime 0.85.1-session-v16-20260917. API health and manager active verified; deployed backend/runtime source hashes matched. Existing real v15 environment was first preserved, then upgraded only after confirming idle/no pending dialog/no background jobs; same platform session and durable history retained and new process running. Workers unchanged, global maintenance not enabled. Rollback releases/pi-context-permissions-20260917-rollback. Full upstream Pi parity goal remains incomplete; this finishes the newly authorized permissions/memory/entry-point slice.
