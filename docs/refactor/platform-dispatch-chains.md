# 平台关键分发链

本页基于当前重构工作树源代码检查；调用可达不等于业务成功。AR 详见 ar-execution-chain.md；完整装饰器/调用表达式索引保留在 execution-paths.md 和 reports/python-call-sites.md。

| 路径 | 入口与调用者 | 分发/副作用 | 运行证据与局限 |
| --- | --- | --- | --- |
| 普通任务创建 | web/src/app/api/platform/runs/route.ts:POST → features/run-setup/api/server.ts:createSafeRun → platformServerRequest('/api/runs') → backend/app/main.py:new_run → run_service.create_run | BFF 校验请求；后端绑定材料、创建 Run，emit_event 隐式提交 | ordinary-e2e 实际测试后端 API 至下载；该测试不启动 Next BFF |
| 普通任务确认与执行 | run-setup/api/server.ts:confirmCreatedRun → /api/runs/{id}/confirm → run_service.confirm_run → worker.run_once → claim_next_run → execute_run → _execute_claimed_run | claim 锁定租约；execute_run 绑定 fence；get_adapter 选择 manifest 指定执行器，adapter.execute 执行；emit_event 更新状态并提交 | 合成 reconcile-bank 匹配 2 笔，两侧各 1 笔未匹配，已登记且下载 Excel 验证 |
| 普通产物下载 | main.download_file → FileRecord 权限/存储读取 | 产物必须有平台记录；普通文件下载和 Pi 工作区文件下载不是同一通道 | ordinary-e2e 验证 skill_id/run_id 与工作簿内容 |
| Native 命令 | routers/assistant.py:native_skill_command（POST /api/assistant/native-skills/{skill_id}/command）→ native_skill_service.execute_command | prepare_context/session_snapshot → command_guard → require_native_skill/require_turn_command → Run 创建提交 → executor.sock → 比对输出哈希 → register_output → 状态/审计提交 | 合成测试被新库 assistant_turns 缺表阻断。当前前端搜索未找到直接命令调用者，只有生成契约及历史 runs BFF；不能据此证明外部客户端无人调用 |
| Native 历史记录 | web/src/app/api/platform/assistant/native-skills/[skillId]/runs/route.ts → platformServerRequest → assistant router → session_runs | 原生独立命令和历史产物仍存在；不能因 Pi 页面替换就删除查询入口 | 仅源码关系，实际使用频率未取证 |
| Pi 对话/工作区 | pi-chat.tsx、pi-workspace.tsx → /api/platform/pi-runtime/* BFF → platformServerResponse → routers/pi_runtime.py → pi_runtime_service | create_session 保存用户范围会话目录；operate 在每会话 fcntl 锁下校验，再请求 manager.sock；宿主管理器按 owner/session 分发容器或文件操作 | Pi 文件专项覆盖文件通道；模型、浏览器和容器启动能力不由此证明 |
| Pi 上传 | pi-file-transfer.ts:fileRequest → sessions/[sessionId]/files/route.ts → routers.pi_runtime.files → require_upload → runtime.operate → RuntimeManager.dispatch → pi_files.operate | begin/chunk/commit，偏移检查、只读输入文件及 SHA-256 | service/UDS/manager 文件链通过；上传路由的 require_upload 与审计 DB 不在该专项内 |
| Pi 下载 | pi-file-transfer.ts:download URL → download/route.ts → routers.pi_runtime.download → runtime.operate → pi_files.read | 后端分块读取并绑定 version；BFF 透传 body 和下载头、请求取消信号，不加默认超时 | 真实后端 StreamingResponse 回读通过；跨用户/会话、文件变化、路径与符号链接拒绝通过；Next BFF 尚无运行测试 |

## 共同 BFF 与事务风险

platform-api/server-client.ts:platformServerResponse 从 platformCredential/credentialHeaders 获得服务端身份，设置 no-store 并调用限制后的平台路径；统一错误转换由 platformRouteError 处理。不得把浏览器传入身份视为已认证平台身份。

普通 Run create/confirm 在当前代码中没有直接 db.commit，而依赖 emit_event 的默认提交。Native 命令包含命令前 Run 提交、事件提交、归档后最终提交；异常回滚不等于已复制产物自动消失。Pi 工作区文件管理通过宿主目录实施，下载路由单独写审计。三者不是统一事务，后续迁移必须分别设计边界。

本轮不删除 Native，不迁移会话，不运行生产任务。部署与调用量未知项继续留在 deployment-entrypoints.md，静态可达性不能用作退役依据。
