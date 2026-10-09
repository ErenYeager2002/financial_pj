# CW-08 控制层施工记录

## 2026-09-29 15:28 控制层提取已上线

按既定平台施工标准，将原pi-chat.tsx中的会话轮询、游标、初始化读取、投递回执、消息、附件草稿、上传和操作封装到use-pi-session.ts。原页面接收view与actions，保留显示、输入框尺寸、滚动及拖放交互。复用原有pi-client、pi-protocol、pi-event-reducer和pi-storage，没有新增服务或替换Worker。此次机械提取没有更改核销算法或运行权限。

源码仅两个文件有别于原前端构建：pi-chat.tsx=02f60ebc1a081cad52da5eca35221ff92fc77f2be8e202a42bbddbe2bfff728d；use-pi-session.ts=4245e821addfbb0eb33353810edec776fb09711702609638733db75c472d318a。TypeScript检查和7项事件/缓存测试通过，离线构建成功。前端镜像sha256:779d9acd43c27f034c6baa443b874a6b9eb6c34d3b6edaf1d14ed2759b9784e5，源清单digest为8d50874619df81703171a4ea66aac56555f08d65a7c59de44014fff94ee8124d。回滚配置/home/lee/financial-platform-isolated/releases/managed-20260929-072717-57c488f6。

现有批次结束后切换，仅更新Next。独立回读镜像、构建清单及两个源码哈希一致，服务healthy、维护normal、活动计数为0。Chrome检查既有会话列表、切换会话、输入到发送按钮联动、清空草稿后的按钮禁用及命令菜单，均正常，错误日志为空。测试草稿带codex测试标识，已清除且未发送；未启动Pi任务、上传文件或执行财务操作。

本次仅完成提取阶段的验证，不声称真实模型消息、上传、确认、取消的完整G4矩阵已完成。下一步处理初始化观察的取消、完整view model及关联子组件控制边界；CW-08和总体施工尚未完成。


## 2026-09-29 15:33 观察取消补丁已上线

初始化和响应后的只读get_messages/get_state/get_available_models/get_commands共用该次轮询的AbortSignal。HTTP适配在发请求前及解码响应后检查取消，因此已卸载页面不会继续下一条初始化读取，也不接收迟到结果。页面取消仅停止观察，不发送stop/abort，不绑定用户prompt、模型变更或正式业务执行的取消信号。

6项新增传输场景中，旧源码精确哈希e8bd6e1d164fa50843cb06e02701a51ad378c269da75ce9d4bd5614ee5efec1e在隔离容器复现3项失败；修复后加上7项事件/缓存回归共13项通过，TypeScript检查及离线构建通过。传输测试使用可控fetch实现模拟取消时序，并非声称已在生产注入断网或运行期取消业务。源码仅pi-client.ts、use-pi-session.ts及pi-client.test.ts改变。

运行前端sha256:995af70ed9b41ff5767f967c8c02acb81f388d90a05d64e2a949b13fd155555c，源清单489cf1252a1fe73e0106f676fb9b9f0bd4b6936bc6448e7554992a81f04d458c。回滚配置/home/lee/financial-platform-isolated/releases/managed-20260929-073220-5d7329f7。独立回读通过，Next healthy，维护normal，活动计数0。浏览器刷新后由助手转到工具中心再返回，能够显示此前Codex验收消息及“收到”回复；没有新增发送、上传或任务执行，错误日志为空。

源码哈希：pi-client.ts=f222036f57c7aaeca22058d6ff0526c443c51378e95f09d25d10924216d66ef0；use-pi-session.ts=38ec216065978a7709523158e90622f06a2ff05f7dd9f04a1b9a27e27889a5eb；pi-client.test.ts=3c01aea4b895c9e75e5dce79527cf1c2187d667c34cfca7b4146f444e8eaac75。完整G4矩阵仍未完成，继续view model与子组件边界。


## 2026-09-29 15:41 连接与执行状态投影已上线

新增纯函数pi-view-model.ts，以连接状态、是否获得活动快照、环境模式、待确认输入和发送/上传/回执状态生成显示与按钮可用性。首次连接、断线恢复和运行中但尚未读取活动时均为unknown；不由旧working=false推导空闲。待工具输入单独显示waiting_input。确认停止的环境允许用户主动发送启动，RPC忙碌时仍可发送follow_up，终端/未知模式禁止RPC变更按钮并给出说明。前端可用性不是后端业务权限；未更改核销算法或后台授权。

usePiSession在每次观察更新连接事实；历史读取失败允许下次只读重试，不把失败读记成已加载。输入提交、模型/思考强度、上下文整理、中断和环境按钮使用新投影。丢失连接时不继续将旧working显示为确定正在处理。TypeScript检查及23项相关测试通过，其中10项投影场景覆盖未知、断线、待输入、终端模式和投递不确定，构建通过，静态差异已检查。

前端镜像sha256:91a82516ecf38fbc2cffcb178e752293a91a687789102d554ad6d7eb19179d99，源清单475e7f8c338e257a005e4ba9557c05176a129a332c6d97a4462ea351c82f0a19；回滚配置/home/lee/financial-platform-isolated/releases/managed-20260929-074018-59386fd1。独立回读源码、清单、镜像及healthy/normal状态通过。

浏览器实际验收：初始显示正在连接，读取历史后恢复操作；在原Codex验收会话7089fbdc-6ca0-40e0-aabc-3775092e86d9发送“codex测试：只回复控制层正常，不调用工具或访问文件”，发送后立即离开到工具中心，再返回看到唯一的新消息和“控制层正常”回复，step-3.7-flash会话模型正常读取，没有会话失败或控制台错误。随后结束本次测试启动的环境，恢复会话环境入口重新出现。未运行财务工具、上传或改写业务材料。生产未注入故障；断线细分时序使用受控传输测试。此项不替代文件/确认/多轮工具完整G4矩阵。

源码哈希：pi-chat.tsx=1e18885cb5f3c868b8dde6379bc98a55212ab362f4d728eee5518418fded8538；use-pi-session.ts=3e09716677011adda36ae776e9ab55592b026b954fa29e37d6d669b4f669a9b6；pi-view-model.ts=a522a063480a750b39be389068195dc1be1668e38c41196daa5e08b7533fea07；pi-view-model.test.ts=944cb81e84a06865447525a2429b06fe5e10b38ee4eead5d47734ce73b10509b。


## 2026-09-29 文件成果控制层：源码及候选已验证，待发布

pi-chat-artifacts改为仅展示view与刷新动作，目录读取移到use-pi-artifacts，下载链接在控制层投影。scanPiArtifacts负责有界递归/分页，保留依赖目录和隐藏目录过滤；请求上限100，文件上限1000，单页过大也不能超出上限。每次目录读取前后检查取消，读取错误不代表完整空目录。usePiArtifacts把结果绑定会话，旧会话的迟到结果被取消，切换后未加载时不显示上一会话文件。连接未知或观察到忙碌时不开始目录扫描。上限触发且文件为零时仍显示未完整读取提示。

TypeScript检查及32项相关测试通过（其中9项目录扫描），离线候选sha256:9a98aa6080a69c0bc642ab4a36f01166d04747d395499c2c72f9629eb3d1b869，源清单4bc672be02395c2f2a1e6734959bb40482882581d0f859937aefac2bc210cc0c。15:51的发布尝试因新28天核销批次尚在执行，等待2分钟后安全退出；未切换Next，维护状态恢复normal。当前运行前端仍为上一段91a82516，不能将文件控制层报为已上线。

等待期间完成原页面文件基线：在既有Codex验收会话仅创建“文件成果验收_20260929_codex测试.txt”测试文本，页面显示写入文件完成、成果链接，浏览器下载成功。下载后核对本地与远程SHA-256均为c4f391c808b4ffd997bb027dac3e7cf1fa971c71affb24b511c19b8292f26b95，34字节。模型未按提示添加末尾换行，但传输字节与源文件完全一致；不把这点描述为换行要求已通过。下载已移入本地.scratch/pi-construction-20260923/artifact-baseline-codex测试.txt；远程仅该测试文件经路径、非链接和哈希检查后删除，刷新成果区确认消失。测试环境随后已结束，未调用财务工具。新控制层的文件浏览器复验仍待上线后完成。


## 2026-09-29 16:08 文件成果与账号缓存保护已上线

前端c874e46a2951d0845b0b573927221851fc6c9e2238e2ee23bed6b7708a8336bb，源清单52457867919235866631e5970c5bdd93836a99ea740746a03a9e311f37b735cf；回滚managed-20260929-080810-3a8414ab。36项针对性测试、类型检查、构建、独立运行回读及浏览器验收通过。账号缓存写入和移除拒绝已切走账号的迟到回调；该时序通过隔离测试验证，未在生产切换两个真实账号。

浏览器复建同名codex测试文本、切空会话无串文件、返回恢复文件入口、实际下载34字节且SHA-256为c4f391c808b4ffd997bb027dac3e7cf1fa971c71affb24b511c19b8292f26b95。文件保存在本地artifact-after-codex测试.txt，结束测试环境后按路径与哈希清理远程单文件，刷新确认入口消失。没有调用财务工具。下一阶段为连接未知时工具确认窗口的可用性与请求有效性校验，完整G4尚未结束。


## 2026-09-29 16:23 工具回复门禁已上线

前端8853ffda9ad0f139ab143d97692ccc1793cdb33936b328c9b0906e56dd21589a，源清单9f8ebb6eaded6c612db67c7a8019a290fce8d464b6dcea2751bf44e292ba1c31，回滚managed-20260929-082244-1c0b2443。42项针对性检查、类型检查、构建、独立回读通过。断线/未同步/停止/终端模式禁用工具回复；提交时检查请求仍存在、未过期、响应类型有效。后端仍独立验证。

真实浏览器通过确认、选择、文本输入、刷新恢复未完成请求、5秒请求自动结束。使用临时本地编写的扩展，严格限定测试会话7089fbdc-6ca0-40e0-aabc-3775092e86d9；未调用模型或财务工具，未放宽工作区信任。浏览器后退曾出现URL变化但内容仍在工具中心，刷新后恢复，尚未确认根因，不记为后退导航已通过。

验收发现等待扩展回复时发送状态优先于等待用户提示，已进入下一补丁；不修改投递锁或放行重复请求。测试扩展在后续复验后清理，完整G4仍待继续。


## 2026-09-29 16:32 等待用户回复提示已修正并复验

前端952292723c914d66a62b03a3e0b03f18c83f216c4a2cc0b52a68ed28d89a2b51，源清单f54c7d821fdf809d5634ce1db20dc81daa9482cff6c1dd8f0b77a51ace476690，回滚managed-20260929-083139-cfa97aa2。43项针对性测试、类型检查及构建通过，独立回读healthy/normal与源码一致。显示优先采用连接未知、等待用户的事实；原发送准入锁不变。

真实浏览器显示等待你的回复和禁用的等待回复按钮；拒绝确认后扩展收到false，取消选项后收到undefined，取消文本后请求结束。此前确认true/选择乙/文本和5秒过期路径已通过。测试全程不调用财务工具，未放宽工作区信任。测试扩展实际存放在该账号home，具有固定会话环境变量检查，其他会话不注册命令；完成后已停止本次环境并按精确路径与SHA删除该扩展，初次工作区临时副本也已删除。本地保留源文件及验证记录。

后续继续CW08完整G4：后退导航异常待复现，扩展display消息的展示/历史恢复待协议核实；不能将全部原有功能和全部状态竞态标为完成。


## 2026-09-29 16:40 会话导航修正和附件验收

前端e7ad3eb9d8c465c5407b26ae9102dbd106c14923eba1a2a04291ce0bf84221d9，源清单2b494be064a634fbe01eb55c2a4dc20e2522e13e6c7bde78e8719fabf8cb067d；回滚managed-20260929-084010-ba5d1e1b。43项相关检查、类型检查、构建和独立哈希/健康回读通过。聊天与辅助终端不再直接replaceState(null)，改用框架路由且地址相同时不重复修改。

原浏览器复现先前连续失败：刷新聊天页、进入工具中心、后退，地址恢复但会话区域不出现。修复后同一路径恢复正确页面，会话7089与空会话3ac切换地址和内容一致。原问题涉及原生历史状态与框架路由的初始化时序；不新增不能覆盖该时序的浅层单测来替代浏览器回归。

另完成控制层附件G4实测：本地附件分片验收_codex测试.txt共1048593字节，经真实上传完成两片，刷新仍恢复同一草稿。远程SHA7c40713f960859d5e0ed86db6c27bf1e6c0533b138b45f82ace495ba5427874e与本地一致，文件权限0444。没有发送给模型或执行财务任务。界面移除草稿后，按已验证UUID/路径/哈希清理该单文件及其空目录，本地原件保留。


## 2026-09-29 16:56 visible extension messages

Stopped-history reader and chat renderer now retain only explicitly display=true custom messages. Internal/hidden entries remain hidden; private extension details are not copied into the history wire object. Before-fix regression: 3 failures among 4 initial tests; final 7 isolated history tests and 44 frontend tests/typecheck passed.

Manager history module e82ccfb2 deployed, rollback managed-20260929-085353-pi-visible-history-15e73f07. Unit source and installed SHA 7e0ee79c matched before daemon-reload. Manager restart preserved all existing Pi container IDs, PIDs, running flags and start times. Existing terminal environment was not stopped.

Frontend 531a507e122fd152ac84cfbb97ee27b8bc54f8443dbf2f528baf549fa3c1aa4e deployed, manifest 3d27cd1db20de3c31f241e36b8d5bed28a92117507c693d54a7d4bceee3886dd. Rollback managed-20260929-085418-54d663d5. Independent image/source/health/mode readback passed. Browser own synthetic session 7089fbdc shows exactly two expected extension results both stopped and live. Own environment stopped after verification; browser error log empty. No real finance task, commit or push.

CW08 remains open: next validate abort/queue behavior and capability boundaries against installed Pi 0.85.1. Current interface sends abort only; installed SDK supports separate clear_queue. Need preserve distinction between reply, background job and financial workflow cancellation.


## 2026-09-29 17:10 reply interruption and queue choice

Frontend 02ad8ae8794caf784e3c2cec12517e1607758263240e407118239eb6b30867f4 deployed; manifest ee8d9370ef84ee2d3994e82ce7a135a68dd30ddbd817ebcb61d89b7ce83f0d10; rollback managed-20260929-090519-3b047c33. Independent source/image/health/mode readback passed.

UI distinguishes abort-only from clear_queue then abort. Clear waits for actual Pi RPC acknowledgement before restoring returned queue text to composer and dispatching abort. HTTP accepted alone never completes control. Bounded acknowledgement timeout, exact ID+command matching, disposal/generation guards prevent dependent control replay. Queue updates use current SDK queue_update events.

Validation: prior 44 frontend cases pass plus 9 new control tests; first control-test load failed because native Node strip mode cannot load TS parameter properties, fixed syntax then all 9 pass. Typecheck and build passed. Browser synthetic text-only test queued one follow-up (UI 1 pending), chose clear-and-abort, received confirmed notice, original queued text restored with no queued reply execution. Abort-only branch separately confirmed. Model selection changed from platform-default alias to step-3.7-flash and back with observed server-driven selection. No finance tools invoked; test environment stopped.

Next defect reproduced in browser: an unsent text draft disappears on refresh. Draft persistence source is being added under authenticated account/session scope; sent text must be removed before dispatch so reload never promotes an uncertain delivery into a fresh draft. This next change is not yet deployed.


## 2026-09-29 17:34 text draft recovery

Frontend b1d177824cca6e64b3e020dd24e625c720c5d71ebe0a9112747461e3639fab5c deployed after the real batch finished. Manifest 2320acc23db06212b691cb22893cc844691b20c0e94c048f12226236069139fd; rollback managed-20260929-093132-dfa88b37. Two earlier attempts drained safely back to normal without changing Next while the batch remained active.

Text drafts are sessionStorage scoped by authenticated owner and session, with no import of unscoped legacy text. Submitted text is removed before dispatch; edits made while starting are retained. A definite RPC rejection preserves current draft; uncertain delivery does not automatically restore sent text for replay. All 56 related frontend tests/typecheck, target diff review and build passed. Independent live image/source/health readback passed.

Browser original red repro now passes: unsent text survives refresh. Session 3ac08dab stays empty while returning to 7089fbdc restores its own draft. Sending a unique text-only synthetic prompt then refreshing yields exactly one user message and one expected reply, with an empty composer. Own test environment stopped afterward. No financial tool was used.


## Delivery evidence projection deployed 2026-09-29 18:03

Frontend 05a2298fc20e565f662c57f0bd169fef43b90676082f853193712c1930509b64; manifest ab58df7a71332631d08dc6b29dfc9a6c50740491864bde36c476fb5cb3624dc5; rollback managed-20260929-100235-8a746352. Durable legacy pi_accepted now projects as transport_accepted, not actual Pi acknowledgement. Only matching live RPC response confirms/rejects delivery. Late HTTP results and older RPC responses cannot overwrite a newer delivery/draft. Submitting remains an admission barrier even if an older agent_settled arrives. Unknown/transport-only recovery never resends automatically.

62 related frontend tests and TypeScript pass; scoped diff check and offline production build pass. Running manifest/source hashes, health and normal mode verified. Browser unique synthetic prompt 1004 got actual Pi acknowledgement plus exact reply; reload showed exactly one user message and one reply. No finance operation. Browser connection changed from Chrome 1 to Chrome 2; refreshed inventory and new isolated QA tab recovered control without user intervention. A refresh-before-ack case and durable storage of actual RPC acknowledgement remain unverified/not implemented, respectively; no claim of full G4/CW09 completion.


## Startup observation barrier deployed and browser accepted 18:34

Frontend 6ae5d1e7f0fab5a2bedc5ccb9d574507ba15703397c964f3e74ce8103fa5de78, manifest abe3ca7fc517bc472a8fd6441c46cd0dd094daaea4e0496aae6d9e0ad14d4851, rollback managed-20260929-103029-2c53a638. Source/runtime hashes and health verified. PiStartObservation waits for a fresh post-start poll with matching generation, RPC mode, real instance and activity; reducer reset/gaps do not release the first prompt. Timeout/unmount rejects without dispatch or automatic restart/replay. Five new tests plus prior cases total72 and TypeScript pass.

Browser1032 cold start and1034 same-page stop/restart both yield actual Pi acknowledgement and exact reply, empty composer, no unknown-state error. The latter repeats the original1013 failure sequence without refresh. Exactly one user prompt/one reply and no browser console errors. Own test environment stopped; other environments untouched.

Related boundary verification:18 isolated PostgreSQL/HTTP/file/admin-stop/receipt cases pass. Initial test setup needed root only inside the disposable network-isolated test container; old admin-stop fixture lacked the now-required exact container identity. Fixture updated to current Id/Name protocol with an added changed-owner rejection case; no production guard weakened. Test source SHA335d09c8031a4dd1816ee5517042ec6dc726ba15c668e08b126b8dc13a8bb5b9. Test resources cleaned by exact owned labels. No additional production restart for test-only change.

Another AR release advanced backend to ebd548185c7a39352218c90fc7dae9e7293306ae8843f9e74df0278f64adc956. Readback confirmed API+twoWorkers preserve current Pi route/contract/capability/runtime source hashes; no rollback of the other release. Read-only live registry inventory:21 fixed records (2 published,19 disabled),16 native pinned packages,0 registry errors; all native package trees safe and content hashes captured locally. Native index lacks structured external-system/recovery metadata; do not invent it or make a new mandatory author manifest.


## 2026-09-29 Queue retrieval acceptance and requested pause

Frontend deployed: sha256:46d35074a0c9df3e5bae496b7021964d13f6fba5ea2ef69a4ad67fa3b2d5d5c2.
Build manifest: a92a6b7ace9757c2f5a2486b49278c8fad83617bbf9f7669bac6044f284608e1.
Rollback: releases/managed-20260929-114912-5b8603d5.
Independent readback confirms running image, source hashes, healthy Next and normal maintenance mode. Active financial task counts were zero at readback. 74 targeted frontend tests, TypeScript and production build passed before deployment.

Queue retrieval now waits for the actual matching clear_queue RPC response and restores returned steering/follow-up text to the composer. It does not send the restored text or abort the active reply. Retrieval is unavailable while a send acknowledgement is pending or delivery is uncertain, preventing a late acknowledgement from clearing restored text.

Browser acceptance on own synthetic session 7089fbdc-6ca0-40e0-aabc-3775092e86d9: test1955 queued one follow-up while a harmless sleep command ran; retrieval removed the pending count and restored the exact text to the composer. The active reply continued and the retrieved message did not appear as an executed user message. The draft was then cleared, the wait explicitly interrupted, and the own environment closed through the UI. No real financial operation was run; other environments were untouched.

Test1953 also confirmed that abort-only does not discard the queue: the queued message proceeded after abort and produced its response. This is not a promise that the queue remains dormant after interruption. The existing dialog warns that retained messages may continue. Users who intend to withdraw queued work must retrieve it or clear the queue when interrupting.

User explicitly requested pausing after this round. This round is deployed and browser accepted; no next-stage implementation started. Whole construction plan remains incomplete: broader G4 acceptance, remaining CW09 mode/external capability boundaries, conditional CW10 UI work and CW11 final gates remain for a later resume. Durable bridge acceptance still must not be represented as a persisted actual Pi RPC acknowledgement.


## 2026-10-08 observation scheduling round deployed, accepted; pause requested

Frontend `cfd960509a9e013af1d24f35e5ed0cd9d49cf639a30fe54cbdf6b57aca9f0c10`, manifest `8ca80c9201a8163e6f04df73af840af0898bcc72df28bdc94464ac8ebd3a3235`, rollback `managed-20261007-224853-ed0cf650`. Eighty targeted frontend tests, TypeScript, build, scoped review and independent live readback passed. Browser acceptance verified five-second controlled hidden observation, cancellation of an old held read, fresh-state control admission, preserved drafts and no replay across actual UI navigation. See [bounded acceptance evidence](pi-cw08-observation-acceptance-20261008.md), including the visibility-injection and idle-runtime limits.

Owned synthetic environment7089 is closed, test injection removed and draft cleared; other environments untouched. User requested completing this round and then pausing. This round is complete; the full construction goal is incomplete, and no next-stage implementation has begun.


## 2026-10-08 F1 completed; construction resumed

The latest user continuation supersedes the prior pause for ongoing work; earlier pause records remain historical. F1 complete-domain abandonment safety is deployed and read-only browser accepted. Fifty-two targeted cases and one actual PostgreSQL case passed with zero PostgreSQL skips; the earlier six-pass/one-skip run did not establish PostgreSQL coverage. Backend cddc9fea86f0e81ee86170a73a47dbaf53c1a5ac13ae149160b2c72f9557dfd6 and three runtime files match source; API healthy, two Workers running without Docker Health, normal mode and five active counters zero. Frontend cfd960 is unchanged. Three legacy markers remain unchanged, one needs investigation; current-scope zero blockers is not a claim that every historical unknown has cleared. Actual UI shows the investigation reason without resume/unlock controls; no financial recovery was performed. See [F1 release and acceptance](ar-cw06-abandonment-scope-20261008.md).

Full construction remains incomplete and active. Next F2, then F4 / F5 / F3 / G4 / CW09 / CW10 / CW11. This record does not declare a new pause or full G4 acceptance.


## 2026-10-08 F2 completed; construction continues

F2/A24 按可用容量领取已上线并完成只读浏览器验收。真实隔离 PostgreSQL 11 项通过、0 skip，原 execution snapshot 23 项通过，最终双轴静态复审0阻断。API及两Python Worker均为85bb307cf1b4625dc5e38692f8878d59217733905eba1d67ae854e550ef54ba0，worker源码/运行cac2ff匹配；API healthy、Worker running（无Docker Health），normal、活动计数0。F1、scheduler、前端及独立AR修改保留；旧marker未改，其中1条待调查。浏览器任务中心/工具中心/核销创建/旧封存警示通过，未进行财务操作或提交推送。详见 [F2上线与验证](pi-cw07-run-claim-capacity-20261008.md)。

本条仅完成 F2/A24；整体继续 F4.A，各次执行记录只读展示。F4剩余、F5、F3、A25、G4、CW09、CW10、CW11未完成，不自动暂停。


## 2026-10-08 F4.A accepted; continuation checkpoint

F4.A各次执行元数据查询及页面展示已完成源码、13项专项验证、双轴审查、前后端上线和真实只读浏览器验收。history不授予恢复/解除，原F1/F2与历史待调查占用保留。API/两Python Worker为dca460，前端b8990a，normal且健康；本阶段未提交推送或进行财务操作。详见 [F4.A记录](pi-cw06-attempt-history-20261008.md)。

当前节点：F4.A完成，整体目标active。下一步F4.B不可变prepared refs锚点及故障窗口TDD；多attempt调查/条件处置、F5、F3、A25、F6、G4、CW09、CW10、CW11尚未完成。AGENTS新规则同步三入口5ea6a，用户Token口径为上下文容量接近上限保存节点。
