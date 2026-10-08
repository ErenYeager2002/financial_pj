# CW09 boundary progress — 2026-09-29

## Public operation contract (source and candidate, not deployed yet)

The API now validates the inner operation before dispatch to the host manager. Owner identity remains computed from the authenticated user. Supported public RPC commands match existing page controls: get_state, get_messages, get_available_models, get_commands; prompt, steer, follow_up; set_model, set_thinking_level, compact; abort, clear_queue; extension_ui_response. Unsupported commands and unknown fields return 422. This is not a promise to expose the entire Pi SDK as a web API.

Existing terminal transport remains available through terminal start, base64 data and resize, under existing ownership checks. This change does not add a new execution mode or new host access. It does not remove Pi's already installed internal tools. Jobs API retains list/poll/cancel; it does not gain arbitrary command-start capability. Dialog shape is checked here, while pending-ID, method, option and expiration authority stays in the bridge. Files keep their separately versioned file contract.

Source module pi_operation_contract.py SHA 5e6661b8099dc60ba5b231455f4cd3e91fd2daa87f793e2ceec598d3520e5168; integration pi_runtime_service.py SHA e332cffe391f3042ee2a25599e6c63c48302dd1fa454886cef7049eaf56e4971. Tests: 7 unittest groups covering malformed discriminator types, identity/path/approval injection, retained UI controls, terminal transport, job restrictions, dialog shape and rejection before host dispatch. Four existing durable-receipt tests pass. Candidate image 3e1997fccd557fb5e76213a9540c917b8820ec0fe1dbfd0b5c78267852e8ac59 built on live backend base 6d8c7ba5324ef9c859c9691e42b279790f47cd66d1d2d66fc44492c84eb1330d, copying only those two modules. The seven groups also pass inside the candidate image.

## Existing boundaries inspected

Business delegation remains pi-business-read-v1, validates active identity, password epoch and session. This is not a new financial task submission tool. Downloads use attachment/octet-stream/nosniff/no-store, and transfer chunks include a fixed version. Existing file tests cover ownership/session separation, path traversal, symlinks and changed files; they were inspected here, not rerun during this stage.

## Remaining work

Deploy the candidate only after active real workflows finish; read back API and worker hashes, then browser smoke-test allowed operations. Capabilities/registry projections, explicit business-versus-analysis inventory and broader permission acceptance remain open. No new financial write tools are authorized by this document.

A separate delivery evidence gap was identified: durable state named pi_accepted currently comes from successful bridge stdin write, not a Pi RPC response. The frontend may subsequently observe actual acceptance/rejection, but a refreshed durable receipt does not retain that distinction. Preserve no-replay guarantees when separating transport evidence from actual Pi acknowledgement. This has not been fixed by the operation-contract change.


## v2 candidate refinement (not deployed yet)

Revoked Skill grants still permit the active owner to inspect poll/get_state/get_messages, abort/clear_queue, inspect or cancel owned jobs, and reject/cancel a pending extension dialog. They do not permit new prompts, positive approval, model changes or other new work. Every operation still validates active account identity and owner/department scope; start retains separate requested-binding authorization during provisioning.

Latest module SHA 7d2ec85b40a13480002fffe7c6fbed063ef70e85331047c47195046c9e47eefb; service SHA c2553e8867f2c77e8877f71c8fb16e6ecb0568651d4ec84dd99389f31f3dd3e2. Ten unittest groups and four existing receipt regressions pass; ten groups also pass in candidate image 58e1655a31d7da58c7efa9043f892a454f88e69b0a55cba5a907b9d1439b24f8. This supersedes the v1 candidate, still based on live 6d8c7ba backend with only two modules replaced. Waiting for the existing retain_files.py deployment lock to be released; no forced lock release or interruption.


## Deployed and verified at 17:43

v2 image 58e1655a deployed with rollback managed-20260929-093549-9f036ae3, then browser chat/model/stop smoke accepted. Follow-up wire-limit regression reproduced three failures (invalid UTF-8 surrogate, JSON-escaped payload exceeding bridge limit, multibyte payload exceeding bridge limit). The validator now measures the same UTF-8 JSON plus newline as the bridge, before receipt dispatch markers. Eleven unittest groups pass, including all three formerly failing cases.

Current backend image 1df52b433a09603ef101f1035778072693a4ca941ed9e61bdc5a760a3304827a is deployed to API and both Workers. Rollback managed-20260929-094128-6549c94a. Current service SHA c2553e8867f2c77e8877f71c8fb16e6ecb0568651d4ec84dd99389f31f3dd3e2; contract SHA 8c5ef4cc220f2fe22929fcc39314310b1969e2ba22d0d627a9450f0a44b8bc7c. Independent runtime hashes, service health and normal mode confirmed. Browser sent a unique normal Chinese text-only prompt, received exact reply, and stopped its own environment; console errors empty. No real financial task or permission change was performed.

Whole CW09 remains open beyond this public-control contract. In particular, do not treat durable transport receipt pi_accepted as a persisted Pi acknowledgement; correct UI projection and recovery handling next.


## Public route validation deployed 18:11

Malformed job operation arrays/objects reproduced HTTP 500 before the service validator. The route now uses the same validate_operation before provisioning or dispatch. All five failing subcases now return 422; supported jobs.list remains compatible. Three route tests passed in source and candidate. Image 04bda1518650f167166b33fe88d63e9e24f88eecee68d74357ef9471b2d32870 was deployed, preserving intervening AR backend 6953dbec changes; rollback managed-20260929-101036-4d3d4baf. Browser unique text1013 got exact reply. Its resumed environment caused a generation reset before client acknowledgement correlation; UI honestly retained transport-only uncertainty. Querying receipt did not replay; history had one message/one reply, manually checked and draft cleared. This is a confirmed startup-observation race to address next, not full recovery acceptance.

## Session permission projection deployed 18:22, browser acceptance in progress

Read-only capabilities endpoint projects the current authenticated identity and the owned session's explicit bindings through existing can_run/can_upload grants. General sessions do not receive every installed Skill. It lists only public RPC commands already allowed by the shared contract; no new execution mode, tools or privileges. Unknown authorization blocks new work. Revocation retains observation, stop and negative/cancel dialog response, while positive approval, sending, model changes and upload are disabled. Backend remains authoritative on each actual action. Frontend refreshes projection every 15 seconds and clears it on connection errors; stale projection is not execution authority.

Backend f711ead5884ae572c61ae13a6462140a00f80f578bab8258ff04f4d5edf5bf1e, rollback managed-20260929-102052-de77dc54. Frontend 51658be2a66d007a89cc2995a7817d942541c6244a0f6666d7b8576913126288, manifest111bda8d834990a01d688bfb94eb3b2991b862ba217321e1c14900b508c280f3, rollback managed-20260929-102151-a0c0437b. Seven backend projection tests, four HTTP route tests, 67 frontend tests/typecheck/build pass. Independent running hashes and normal healthy state match. Browser normal-user flow pending; revoked identity/foreign owner scenarios are isolated tests, no production grants changed. Whole registry inventory and full G4/CW09 acceptance remain open.


## Browser permission acceptance 18:25 and startup follow-up

Own synthetic session7089: capabilities loaded, upload button and permitted model controls enabled, prompt1023 got actual Pi acknowledgement and exact response, model switched to step-3.7-flash then restored platform default. Own environment stopped through the environment panel; stopped state verified and other two environments left untouched. No real grants changed.

Startup race confirmed in the previous resumed session: connect returned after /start, allowing prompt before polling consumed the new instance/generation. The subsequent reducer reset cleared pending RPC correlation. Candidate fix waits for a fresh poll issued after the start response, matching RPC generation and a stable activity observation, before dispatching any message. Timeout/unmount retains draft and reports message not sent. Source plus five new gate tests, 72 frontend tests/typecheck and scoped diff check passed; production build is in progress, not deployed yet.
