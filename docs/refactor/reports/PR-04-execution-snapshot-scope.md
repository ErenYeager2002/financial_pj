# PR-04 执行确认快照：当前缺口与兼容边界

当前input_snapshot_hash仅绑定parameters_json、files与skill_hash，adapters.py实际request.json还包含run.message。preconditions.assert_run_input_snapshot确认/执行复核同样不比较message。已确认这是执行快照覆盖缺口，不声称已证明存在可供普通用户修改任意任务消息的公开接口。

PR03提交幂等canonical_request已经覆盖原始request.message，PreparedPayload.run也保存消息；但提交防重复和执行前完整绑定是不同边界，不能用前者替代后者。模型选择在普通Run主要用于参数解释，执行协议实际读取字段应以adapters为准，不将未使用的配置随意加入强制执行依赖。

实施需要显式版本化执行快照，将message、固定owner/department、Skill身份/版本/内容摘要、执行adapter、已解释参数、文件绑定、确认要求按规范序列化。保留既有input_hash含义，避免无标识直接换算法导致旧任务误判。input_hash列仅64字符，不能直接加前缀；PreparedPayload使用version Literal[1]和extra forbid，添加字段需同步序列化兼容；也不能把版本标记藏进Skill manifest，因为其语义需与固定包比较。

历史处理必须区分：新提交生成新快照；可由既有固定提交记录或PreparedPayload证明的历史任务可按证据验证；缺少原始证据的任务不得用当前可变行重新计算后冒充旧确认。历史查询与已完成任务不受影响；正在原子执行的任务不强制中断；恢复/重试遵守现有新提交和财务禁止自动重跑规则。

下一实施应先选择显式列或独立快照记录及迁移，补新旧PreparedPayload、消息变更、归属/固定版本变化、等待确认/排队/启动和回读兼容测试，再部署。不能用接受任意旧哈希的fallback掩盖新任务绑定失败。以下为最初审查依据；本轮实现与验证状态见文末。

## 已定位的统一写入位置

persist_run 是普通直接创建与 persist_submission 绑定流程共同使用的无提交入口，在Run flush后初始化步骤及审计。优先采用独立run执行快照记录：在此入口与Run同事务写入带schema_version的规范化摘要；确认/领取/启动通过run_id加载验证。这样既有input_hash和PreparedPayload v1保持原格式，不需向manifest植入字段。

历史可信来源为绑定同一scope/run_id的IdempotencyRequest.prepared_payload_json，而不是仅pinned_revision中的原始请求（原始请求不等于模型解释后的执行参数）。历史补齐只能在旧payload、固定Skill、输入哈希、owner/department等全部对应时执行，不以当前行自行生成后直接通过。没有足够历史证据的处理须在正式兼容矩阵逐类列明，不允许无条件fallback。

迁移、快照行不可修改策略、普通/草稿/重试的共用创建、历史回执恢复、确认与Worker拒绝分支及回滚镜像都需要同一切片落实。最初设计已进入本轮实现，线上生效仍须以部署回读为准。


## 本轮源码与兼容处理

已在持久化源码加入 run_execution_snapshots 表（f4b5c6d7e8f9）及版本 1 执行意图摘要。persist_run 与任务同事务创建；确认、领取、启动均校验，原 input_hash 算法与 PreparedPayload v1 不变。记录仅通过受控创建入口写入，应用没有修改接口；这不等于数据库管理员无法直接改表。

绑定字段为任务及所有者/部门、Skill 标识/版本/commit/内容哈希、manifest 摘要、adapter、worker_pool、完整消息摘要、解释后的参数、文件绑定和确认要求。合法的确认时间、确认人、状态、进度、租约仍可更新。消息不额外复制明文。

兼容矩阵：新提交直接创建快照；已有快照任务必须精确匹配；旧任务仅在唯一同归属 bound 回执的 PreparedPayload 与当前执行意图及旧输入哈希全部对应时补建；旧回执缺失、损坏或不匹配则拒绝确认/领取/启动，不从可变当前行自行补签。历史查询和已经完成的任务不回写，也不自动重试。

本轮还保留了另一会话已发布的 AR 变更；具体版本、文件清单及候选/线上核对见 PR-04-execution-snapshot-business-base.json 和后续运行证据。此处不代表部署已完成。
