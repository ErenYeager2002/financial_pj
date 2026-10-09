# CW10 / R13：DeerFlow 展示组件移植（renderer 级）— 2026-10-08

状态：源码完成、类型检查与生产构建通过；**未部署、未做浏览器验收、未切换默认 renderer**。生产默认切换仍受 G1–G5 与 UI 切换批准约束。

## 移植范围（上游固定 d3a9c123，MIT）

| 平台新文件 | 上游来源 | 适配 |
|---|---|---|
| `web/src/features/pi-runtime/deerflow/deerflow-conversation.tsx` | ai-elements/conversation.tsx | 去掉 use-stick-to-bottom（沿用 pi-chat.tsx 现有跟随滚动，不新增锁定依赖）；保留布局与空状态原语 |
| `web/src/features/pi-runtime/deerflow/deerflow-messages.tsx` | ai-elements/message.tsx | 只取 Message/MessageContent 外壳语义（is-user 右对齐气泡 / is-assistant 通栏）；消息协议用平台 `ChatMessage`，Markdown 用平台 AssistantResponse，附件解析与可见性规则与旧 renderer 逐条一致 |
| `web/src/features/pi-runtime/deerflow/deerflow-tool-call.tsx` | workspace/messages/tool-call-details.tsx | LangGraph ToolCall 类型换成平台自有 props；工具名/调用ID/输入/结果四段 Payload + 复制；状态：执行中/已完成/执行出错 |
| `web/src/features/pi-runtime/deerflow/deerflow-chat.module.css` | （样式按上游类名语义重写） | 只用平台主题 token；`prefers-reduced-motion` 降级；操作行 hover/focus-within 显现 |
| `web/src/features/pi-runtime/deerflow/NOTICE` | LICENSE | 完整 MIT 文本 + 固定 commit + 逐文件来源映射 |

开关：`pi-chat.tsx` 内 `renderer` 状态（URL `?renderer=deerflow` 优先，其次 localStorage `pi-renderer`），只在 `PiChatMessages`/`DeerflowMessages` 二选一；「会话设置」菜单加"切换展示样式"项（写 localStorage 后刷新页面，刷新只重新观察，不发新 prompt）。**单一 usePiSession 控制器不变**，新旧 renderer 接同一 view/messages，无新增 observer、无新增请求（R13-T01/T03 构造层面成立）。

## 明确不移植（沿初审结论）

- input-box.tsx（105KB，非独立组件）、use-thread-chat.ts（会话所有权归平台）、artifact-file-preview.tsx（iframe 允许 script/form，保留下载策略）、virtual-message-list（react-virtual 成本未测）、code-block.tsx（shiki 原始 HTML 路径本轮不开）、prompt-input 上传/提交行为（平台上传/草稿/投递控制器不变）。
- 无后端能力的功能（goal/todos/subagents/长期记忆/历史分支/重新生成/MCP）不展示（R13-T04：界面无伪按钮）。
- 不引入 LangGraph/Redis/Gateway/第二 Next；**package.json/pnpm-lock 零改动**（R13-T01 无新后端请求依赖）。

## 依赖闭包与许可

新增文件 import 闭包：`react`、`@tabler/icons-react`（平台既有）、平台内部模块（pi-message-images、pi-file-transfer、pi-message-visibility、pi-chat-messages、AssistantResponse、 deerflow 内部三个文件）。**新增运行时依赖 0**。MIT 版权与许可文本保留于 deerflow/NOTICE。

## 验证

| 检查 | 命令/方式 | 被测版本 | 结果 |
|---|---|---|---|
| TypeScript | 官方构建镜像 refactor-pr03-builder-e052d65b 内 `pnpm install --frozen-lockfile && pnpm typecheck` | 工作树 6476660+F4.A 未提交+本轮 | 通过（tsc --noEmit 无错误） |
| 生产构建 | 同镜像 `pnpm build`（next build --webpack） | 同上 | 通过（exit 0，全部路由生成） |
| 旧 renderer 不回归 | pi-chat-messages.tsx 零改动（仅 pi-chat.tsx 增加条件选择与菜单项） | — | diff 审查 |

未执行：部署、浏览器新旧 renderer G4 对照、性能对照（构建体积/RSS/内存）、真实会话验收。部署暂缓原因：compose 的 next 服务 pin 与 F4.B 施工会话共用部署根，避免并发发布冲突；待其窗口空出后按原发布流程（发布锁、notice/drain、健康回读、回滚快照）发布，默认 renderer 保持经典。

## 回滚

renderer 级回滚 = 菜单切回经典或清 localStorage；代码级回滚 = 删除 deerflow/ 目录并还原 pi-chat.tsx 四处增量（import、renderer state、条件渲染、菜单项），不影响 Pi 会话、回执、材料与财务任务。

## 部署记录（2026-10-08 11:52 GMT+8）

- 计划 `deerflow-renderer-web-20261008` succeeded：next-1 切换至 `sha256:d177e8ea4802a55c8c49c181f694340cafc4fdcf1baf3a80a2d37024e0a11983`（source_digest `3281996d…9756`，545 输入，与基线 b8990a 差异仅 R13 六文件）。
- 流程：deployment.lock 非阻塞占用 → preflight → notice → drain（活动计数 0）→ full → compose 仅改 next image → cutover → 健康回读 → normal。回滚快照：`releases/managed-20261008-035215-7cdf1a8c`。
- 回读：next-1 running（新镜像）、maintenance normal、网关 8443 → 307、api-1 healthy 未受影响（Up 2 hours）。默认 renderer 仍为经典；新样式经「会话设置 → 切换展示样式」或 `?renderer=deerflow` 启用。
- 自动化（每小时值守部署）已按用户指示改为立即部署并删除。
- 未做：浏览器新旧 renderer G4 对照、性能测量、生产默认切换（仍受 G1–G5 门槛与 UI 切换批准约束）。
