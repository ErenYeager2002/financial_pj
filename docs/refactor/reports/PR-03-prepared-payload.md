# PR-03 可恢复的准备结果

2026-09-20，新建 prepared_payload.py，定义版本 1 的严格字段协议。仅保存任务执行前字段、固定输入/快照信息、模型审计选择和受限 trace 摘要。模型连接配置不整体序列化，不保存 api_key、base_url、extra_body 或原始模型响应；任务 lease/result/终态不能恢复。未知版本/额外字段/无时区时间拒绝。原始业务参数沿用既有输入策略，模块不替代输入敏感信息校验。

恢复生成未加入 Session 的 PreparedRun。ModelAuditSelection 只提供 persist_run 所需审计字段，不带模型调用权限。恢复本身不授权，不证明快照或输入仍有效；接入编排必须重验权限、文件和固定版本，并在同事务内创建 run/steps/events 与绑定 reservation。

验证：prepared-payload 8 项通过；ordinary-e2e 分为正常持久化及 freeze/restore 后持久化两条，2 项通过，均包含真实服务/Worker/文件生成与下载校验，模型响应使用合成 fixture。两条独立测试使用独立意图 key；最初复用 key 命中前例已成功任务，已修正测试隔离，没有改变旧入口幂等行为。AST 和 git diff --check 通过。

尚未接入实际创建、重试、草稿入口。下步必须实现短事务 reserve→事务外 prepare→持久化 prepared→业务与 bind 同事务，验证 prepared/commit 后中断重放及撤权。生产未部署、无财务写入、看板无变更。
