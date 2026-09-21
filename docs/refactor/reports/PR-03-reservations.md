# PR-03 数据库预约阶段证据

2026-09-20，远程持久化源码增加 f3a4b5c6d7e8 迁移，父版本 f2a3b4c5d6e7。新增 idempotency_requests，唯一约束覆盖 owner、department、operation、request_key；状态与绑定字段有 CHECK。models 元数据入口显式导入新模型。runs 仅添加可空 source_session_key/source_command_id 及作用域查询索引，不更改旧 key、不添加旧 runs key 唯一约束、不回填或合并历史记录。迁移为保留绑定的 forward-only，未应用线上。

新增 reserve/read/mark_prepared/bind/reject 底层接口。使用数据库唯一约束和 INSERT ON CONFLICT，状态转换通过 token、租约、作用域及状态条件更新；无内部 commit。准备租约使用数据库时间；已准备 payload 在到期恢复时保留，bound/rejected 不重新领取。operation 使用服务端枚举。调用方仍须执行当前授权、使用原 reservation 固定元数据计算指纹、过滤敏感输入、把业务记录及 bind 放在同一短事务中。底层接口本身不替代这些接入工作。

验证：隔离 PostgreSQL 专项 6 项通过，包括 20 客户端并发仅一个 bound 任务、同 key 异参冲突、owner/department/operation 隔离、事务回滚与成功重放、过期旧 token 禁止绑定、prepared payload 恢复、rejected 不重领。SQLite 5 项通过，真实并发用例按明确条件跳过。新增迁移后的 PR-02 PostgreSQL 事务回归 38 项通过。AST 和 git diff --check 通过。

只读线上检查 normal，五类活动数已为 0。未替换服务、未做线上迁移、未执行财务任务、未操作看板。PR-02 候选镜像仍是之前的 f2 版本，不包含本轮模型/迁移；不要将工作树新 head 当作该候选镜像的 schema head。PR-02 兼容恢复路径仍需解决。PR-03 还缺历史 dry-run、提交及重试接入、快照 TOCTOU、Native 新字段读写与分批回填、前端 key 生命周期及完整验收，不能标为完成。
