# PR-03 短事务提交编排

2026-09-20，新建 submission.py。prepare_submission：当前授权→短事务读取/原子占位→关闭事务→外部准备→当前授权与 token 条件保存 frozen payload。已有绑定直接返回 receipt，不调用模型或重新选版本；已有 prepared 在租约到期被新 token 接管后复用。初次读取与占位之间其他请求获胜时，以获胜登记的 pin 重新比较原请求，异参仍冲突。未取得准备权返回 SUBMISSION_IN_PROGRESS，拒绝状态不重做。

persist_submission：调用方事务内重新授权、读取 receipt、恢复已保存 payload、检查 owner/department、调用业务复核，然后 token 条件绑定与真实 persist_run/steps/events/audit 同 savepoint。绑定及任务提交仍归调用方；失败即使被调用者捕获也不会留下半绑定。bound 资源通过必须提供的当前读授权 loader 返回。应用回调必须按文档契约实现，不得在 callback 内提交或用客户端 operation；尚未适配 HTTP 路由，不能声称平台已具备这一行为。

验证：真实 PostgreSQL 6 项通过，包含 20 并发客户端准备调用一次、任务唯一绑定，固定 pin 下重放不重新选择版本，异参冲突，prepared 到期恢复不重做模型，持久化注入失败的 savepoint 回滚、撤权拒绝、外层 rollback。SQLite 5 项通过，PostgreSQL 并发项跳过。测试首次证明 sqlite3 legacy 模式首个 SAVEPOINT 释放可提前提交，已在本用例显式建立缺失的物理 BEGIN，并保留已有事务；红绿回归证明外层回滚生效。未修改全局数据库事务配置。

AST 与 git diff --check 通过。授权 adapter 使用合成检查，真实用户撤权路径仍须随入口适配验证。下一步：普通 create/retry/draft 各自的 pin、授权、固定准备、复核与 resource loader 适配；前端意图 key、回填执行器与发布兼容方案仍待完成。没有线上部署、数据迁移、财务任务或看板操作。
