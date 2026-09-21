# PR-03 Native 会话与命令标识阶段

2026-09-20，Native 新建 Run 使用 source_session_key 记录 workspace 会话哈希，以 native-run:<Run ID> 生成 source_command_id。不再把会话哈希写入新 Run 的 idempotency_key，旧值不改写。会话查询优先新字段，仅新字段为 NULL 时 fallback 旧 key；两个分支共同限制 owner、department、adapter。废弃任务扫描同样优先新字段，仍校验合法 64 位会话哈希，不扩展路径范围。

新增 backfill_page：默认 dry_run，以 Run ID 稳定游标扫描 Native、限定页大小，返回已扫描/拟处理或处理/跳过/异常 ID。调用者每页拥有事务。仅新字段均 NULL 且旧 key 为已验证格式时补填，UPDATE 再次限定 ID/owner/department/adapter/原 key/空新字段。已有完整身份跳过，部分或异常值报告，不覆盖，不删除、不合并。尚未对生产执行回填；仍需受控执行器与发布验收。

隔离 PostgreSQL 3 项专项通过：作用域隔离与 fallback 优先级、默认只读预览、每页回滚/提交、重复扫描、异常记录保留。真实 Native 服务路径测试通过：合成 UDS executor 连续三条命令，三条独立 Run/command ID、同一会话标识，查询返回全部三条，每次生成文件都独立归档并核对字节/SHA-256。不是实际业务命令或生产沙箱认证。git diff --check 通过。

线上未部署、未迁移、未回填、未执行财务任务。PR-03 尚缺普通任务幂等接入、前端意图生命周期等；PR-02 的兼容恢复与发布仍未完成。看板无改动。
