# OpenCode Go 模型连接

管理员进入模型连接，选择 OpenCode Go，填写 Go API Key 后点击验证并保存连接。
服务地址固定为 `https://opencode.ai/zen/go/v1`，无需填写自定义域名。
密钥使用平台原有加密存储，模型权限和用户隔离规则保持一致。

模型列表从 `/models` 读取，再与已确认使用 Chat Completions 的文本模型列表取交集。
当前包含 GLM-5.3/5.2/5.1、Kimi K3/K2.6、DeepSeek V4、MiMo V2.5、
LongCat 2.0、Hy4 preview/Hy3 和 Omen Alpha。账号实际可用项以连接时返回结果为准。
默认优先 DeepSeek V4 Flash；保存连接或切换默认模型时仍须通过实际工具调用验证。
仅返回模型目录或普通文本不会被判为验证成功。

平台当前模型网关只支持 Chat Completions。Go 中使用 Responses 的 GPT/Grok/Muse Spark，
以及使用 Anthropic Messages 的 MiniMax/千问暂不列出。官方更新模型或协议后，需要更新
对应的兼容名单；不会把目录中新出现的模型自动视为已适配。
Kimi K2.7 Code 也暂不列出：该型号要求思考模式，与平台部分强制工具调用请求不兼容。
参数依据见 [Kimi 官方说明](https://platform.kimi.com/docs/guide/kimi-k2-7-code-quickstart)。

同步请求和流式请求均发送 `Financial-Skill-Platform/0.1` 客户端标识及
`x-opencode-session`。AI 助手按用户和会话区分，Pi Harness 按工作流区分；
会话标识经过 HMAC 处理，不向供应商暴露内部用户或任务 ID。独立请求使用随机会话标识。
只有用户保存连接或主动使用模型时才会发送认证请求；模型密钥不写入源码或日志。

使用限制及接入说明以 [OpenCode Go 官方文档](https://opencode.ai/docs/go/) 为准。
接口与模型协议对照核对日期：2026-09-06。本轮未使用真实密钥完成连接验收。
