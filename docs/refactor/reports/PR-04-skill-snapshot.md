# PR-04 普通工具固定 Skill 快照

基于远程持久化源码，未提交。对应PR-04第5项固定版本检查，包含上一切片普通确认必要条件。当前整个PR-04仍未完成。

## 实现与边界

backend/app/modules/execution/preconditions.py 新增 assert_skill_snapshot 与 ExecutionSnapshotInvalid；backend/app/adapters.py 在读取当前执行owner之后、准备输入及任何外部副作用之前调用。Python/RPA/HTTP共用入口。检查任务固定目录及其后代无符号链接、manifest_path指向该目录的tool.yaml、registry目录算法的SHA-256与任务skill_hash一致；从磁盘解析清单，与DB固定清单语义一致，并校验任务skill_id/version/adapter。

只排除registry.public_dict附加的skill_hash/commit_sha/source三个传输元数据；其他声明及扩展字段仍比较。不切换到当前发布Skill，不用新版本替代历史任务固定包。异常使用SKILL_SNAPSHOT_INVALID，并进入Worker已有前置失败记录。没有新增DB提交、迁移或业务审批要求。

检查与之后启动的文件系统操作不构成外部进程不可改变的原子保证，仍依赖部署保护快照路径。完整确认载荷绑定及全Workflow/AR/Agent阶段授权矩阵未完成。

## 验证

新增7个真实文件/隔离PG用例，旧实现6失败：script、manifest、missing、symlink、database_manifest、adapter。修复后execution-authorization共77项通过，exit0。此前输入用例改用真实有效合成Skill目录，不绕过快照检查。

ordinary-e2e4项通过，exit0，真实registry.snapshot、公用创建/领取/确认/适配器链与合成文件，含prepared序列化还原和并发提交参数；证明真实注册表附加元数据正常兼容。两轴静态审查无确定缺陷；审查建议的实际元数据兼容由该真实端到端链覆盖。git diff --check通过。不执行全仓测试或真实财务操作。

## 保留并行核销更新

用户明确要求保留另一会话更新并合并本轮改动。已保存10项授权源码合并记录PR-04-confirmation-ar-merge.json。另一会话最终镜像d48bf2b825bc与中间ccf155fe9ee6的AR文件哈希相同，backend app与上一轮输入检查一致。源码其余Skill文件与运行包存在历史字节换行差异，没有整目录覆盖源码。

以最终d48bf2b825bc为基础构建候选eb9577118d16及恢复a23938055ebd。两个镜像的正式/实验AR包205项文件哈希均与最终业务基础镜像一致；隔离PostgreSQL、事务、受限恢复检查通过，证据见PR-04-snapshot-candidate-check.json和recovery-check.json。恢复镜像保留确认、输入和Skill检查，提交模式为只允许已有回执重放。

## 发布

并行发布结束后mode/public均normal，三个服务均d48bf2b825bc，五类任务为0；PR-04-snapshot-preflight.json退出0。托管发布exit0。PR-04-snapshot-runtime-verified.json证明三个服务各198个后端源码哈希和205个AR文件哈希一致，UID10001，DB唯一revision=f3a4b5c6d7e8，replay_only=false，restart0，mode/public均normal。前端无构建/重启，未操作看板或真实财务任务，不提交推送。
