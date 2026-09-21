# PR-03 前端错误透传与草稿确认恢复

2026-09-20，PlatformApiError 增加经过白名单解析的结构化提交 detail，BFF server-client→route-handler→client 保留 HTTP status、四种已知提交 code、合法 UUID request_id；不传播 token/trace 等其他字段。缺少 message 的 preparing 提供中文提示。旧普通字符串错误形状保持。run-setup service 使用共享错误转换。

草稿前端原来每次确认先 PATCH；确认应答丢失时草稿已 consumed，PATCH 409 导致永远无法取回原任务。新增 submitDraftRequest：只在 PATCH 409 后 GET 当前草稿，核对 consumed、run_id 及原 parameters/files（对象键不计顺序、数组计顺序）；匹配才重放后端带当前权限校验的 confirm POST。输入不同不重放，403 不额外请求。此修复不绕过后端锁或权限。

使用已存在财务前端镜像的 Node，隔离无网络只读源码挂载运行两份测试，5 项通过，涵盖错误 metadata 往返/字段过滤、无效 receipt、未知 code、确认应答丢失、输入变化及数组顺序、正常与拒绝请求次数。git diff --check 通过。尚未运行全前端类型检查或构建，未宣称浏览器验收。

后续：组件目前仍用 useRef 单一 key，参数变化/刷新恢复需实现；BFF createSafeRun 的最新目录安全检查可能在新版发布后先于后端 receipt 阻断重放，须在保持执行安全策略前提下解决，不能直接删除前置检查。生产未部署、服务未重启、看板无操作。
