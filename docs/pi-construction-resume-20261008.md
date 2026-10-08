# Pi construction: resumed evidence audit, 2026-10-08

This is an observation record, not an authorization manifest. The user resumed the full construction objective after the prior pause. No new production code or permissions were changed in this audit.

## Current runtime evidence

- Frontend image: `46d35074a0c9df3e5bae496b7021964d13f6fba5ea2ef69a4ad67fa3b2d5d5c2`; independent manifest/source-hash check passed; Next healthy, maintenance normal, active business counters zero.
- Backend image: `sha256:dad9726ba9de91b867b76feb0d5788004838f3d2dba940c798ed0113336b0ee5`; API and two Python Workers running. All seven checked Pi service/contract/capability/route/business/binding modules match persistent source. API health is healthy; Workers have no Docker health field, so running is not reported as an independent worker health test.
- Manager disk SHA: `63ad2e891429ac1abce3b2e9e64e8d3bc5afc7d631151bcd51c14fb8bfa1f678`. This audit does not independently prove the loaded process version.
- Structured inventory: [capability register](pi-cw09-capability-register-20261008.json), observed 2026-10-07T22:33:40.051678+00:00.

## Capability inventory

| Source | Count | Execution authority | Missing evidence |
|---|---:|---|---|
| Fixed Registry | 21 | Existing Registry and Worker/workflow, current grants | Per-skill recovery rules have not been audited |
| Native packages | 16 | Fixed commit, explicit session binding, native-- permission key | Structured effects, external systems, recovery, input/output schemas absent from index |

Every entry includes its observed version/content hash, execution source and permission lookup. Fixed entries retain risk, external-source, input/output and network-count fields from the live manifest. Unknown native metadata stays unknown. Registry errors: 0. This does not claim all 37 entries are enabled or business-tested.

## Source-confirmed boundaries

- `backend/app/pi_business_query.py`: query_platform only queries tasks, skills and AR materials. It is not a task-create tool. Skill proposals use a separate route and publication path.
- `backend/app/pi_business_access.py`: business delegation binds session, owner, account status, department and password epoch; checks these on each request. Token values were not collected.
- `backend/app/pi_skill_bindings.py` and `native_skill_policy.py`: general sessions mount no packages by default; explicit bindings are separately authorized; native permission keys remain distinct from fixed tool IDs.
- `deployment/pi_runtime_manager.py:desired_runtime_policy`: read-only inputs and Skill packages; writable home/workspace/context/control; internal owner network with mediated egress. Therefore the historical ADR0006 transient networkless sandbox description is not evidence of current persistent-Pi topology.
- `backend/app/routers/pi_runtime.py`: downloads are attachment/octet-stream/nosniff/no-store and later chunks carry the first chunk version. Public command contract and owned-session checks remain in effect.

## Remaining acceptance and next steps

| Requirement | Evidence status | Next action |
|---|---|---|
| CW08 queue retrieval, startup, drafts | Previously browser accepted; deployed frontend hashes revalidated today | Preserve prior results, do not claim fresh browser regression |
| G4 full real bridge UI matrix | Incomplete | Complete thinking/model controls, reconnect/gap and remaining file/dialog/job scenarios against the browser |
| Browser control | Unavailable on this turn: inventory empty; Chrome and in-app browser creation both unavailable | Retry when browser tool surfaces return; API probes cannot replace UI acceptance |
| CW09 capability inventory | Current field inventory produced; mode/externals/recovery approvals incomplete | Audit missing fields against approved sources without a new mandatory author manifest |
| CW10 DeerFlow | Conditional; G4 and G5 not proven | Dependency/component analysis may proceed; no production UI cutover yet |
| CW11 final gate | Incomplete | Verify remaining caller coverage, recovery and protected-system evidence; no broad cleanup |

No real reconciliation, workbook write, new grant, restart, commit or push was performed. Existing AR modifications and releases were preserved. Full goal remains active and incomplete; this report is not final acceptance.


## 2026-10-08 superseding browser/update record and user pause

The earlier empty-browser-surface limitation was resolved via the dedicated Playwright browser tool. The observation scheduling round has now been deployed and browser accepted; current frontend is `cfd960509a9e013af1d24f35e5ed0cd9d49cf639a30fe54cbdf6b57aca9f0c10`. See [round acceptance](pi-cw08-observation-acceptance-20261008.md). Source/runtime readback passed, mode normal and active business counters zero. Own test environment is closed. The latest user instruction is to finish this round then pause; full G4 and CW09/CW10/CW11 remain incomplete. Do not start another implementation stage until the user resumes.


## 2026-10-08 current continuation and F1 completion

The user has resumed construction; prior pause statements above describe historical state. F1 has completed source changes, production deployment and read-only browser acceptance. Backend is cddc9fea86f0e81ee86170a73a47dbaf53c1a5ac13ae149160b2c72f9557dfd6; source/runtime hashes match, API healthy, two Workers running without Docker Health, maintenance normal, five active counters zero. Existing frontend cfd960 and independent AR balance.37 are preserved. Fifty-two targeted tests plus one genuine PostgreSQL test passed, zero PostgreSQL skips; the earlier six-pass/one-skip run was SQLite coverage with the sole PostgreSQL case skipped. Standards and Spec reviews have no blocking findings. Historical markers are unchanged; one still requires investigation, and zero blockers in the observed current scopes does not clear all historical unknowns. See [F1 evidence and browser limits](ar-cw06-abandonment-scope-20261008.md).

F1 is complete; the entire construction plan remains incomplete and active. Continue with F2, then F4 / F5 / F3 / G4 / CW09 / CW10 / CW11. No real reconciliation, recovery, workbook write, commit or push was performed in this round.


## 2026-10-08 F2 completed; construction continues

F2/A24 按可用容量领取已上线并完成只读浏览器验收。真实隔离 PostgreSQL 11 项通过、0 skip，原 execution snapshot 23 项通过，最终双轴静态复审0阻断。API及两Python Worker均为85bb307cf1b4625dc5e38692f8878d59217733905eba1d67ae854e550ef54ba0，worker源码/运行cac2ff匹配；API healthy、Worker running（无Docker Health），normal、活动计数0。F1、scheduler、前端及独立AR修改保留；旧marker未改，其中1条待调查。浏览器任务中心/工具中心/核销创建/旧封存警示通过，未进行财务操作或提交推送。详见 [F2上线与验证](pi-cw07-run-claim-capacity-20261008.md)。

本条仅完成 F2/A24；整体继续 F4.A，各次执行记录只读展示。F4剩余、F5、F3、A25、G4、CW09、CW10、CW11未完成，不自动暂停。
