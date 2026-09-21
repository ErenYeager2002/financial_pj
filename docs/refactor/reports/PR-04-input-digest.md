# PR-04 普通输入摘要后续校验

远程持久化源码，HEAD 6fce5bf1195c0591d8f8cfb53b84c32c0356f36d之后未提交改动。对应PR-04固定输入/确认前置条件的一部分，整个阶段尚未完成。

## 源码及行为

新增 modules/execution/input_snapshot.py，集中原Run.input_hash公式：按角色与SHA排序的文件摘要，加原参数JSON字节、规范文件绑定JSON和固定Skill哈希。run_service创建与准备复核使用同一函数，没有改变摘要格式或重写历史记录。preconditions新增INPUT_SNAPSHOT_CHANGED，confirm_run在写确认人/时间前校验，适配器在已有Skill检查后、复制输入及启动副作用前再次校验。

输入摘要缺失、参数或绑定变化时拒绝；不把当前内容自动当作旧任务新基线，不自动重跑，不修改财务输入。函数没有新增提交、DB schema或模型调用。

该既有摘要不包含原始message，不防止被授权DB写入者同时更改数据和摘要，不应称为完整请求签名或完整确认凭据。仍需审查完整确认内容绑定与全部执行路径阶段矩阵。

## 验证

新增8项confirm/adapter × 正常/参数变化/绑定变化/缺摘要用例。基线用旧公式独立生成，旧代码6失败，修复后execution-authorization85项通过，exit0。普通E2E4项、草稿提交5项通过，exit0，证据PR-04-input-digest-ordinary-e2e.json及draft-submission.json。两轴静态审查均未发现确定缺陷；git diff --check通过。没有全量测试或真实财务调用。

## 保留另一会话的最新核销更新

构建前检测到线上ar-flow-completion-20260920（c16bec8cca87），后端app保留上一轮快照检查，AR包新增10项差异。按照用户持续明确要求保留并合并；逐项将其源码与上一运行镜像对比（允许纯换行差异），无独立文本冲突，再同步本持久化工作树。没有整目录覆盖。证据PR-04-input-digest-business-base.json包含最新209个AR文件摘要及10项合并前后摘要。

候选d60f2a7c0063与恢复10c5c232fe72均继承c16bec8cca87，209项AR文件哈希全部一致；隔离PG/事务/受限恢复验证通过，见candidate-check及recovery-check。恢复镜像保留所有新门禁与核销更新，只允许已绑定回执重放。

## 发布

预检mode normal、三个服务仍为已核实业务基础镜像、五类活动任务0；托管发布exit0。三个服务均d60f2a7c0063，各199个后端文件和209个AR文件哈希匹配，UID10001、restart0、DB唯一revision=f3a4b5c6d7e8、replay_only=false，mode/public normal，五类活动任务0。证据PR-04-input-digest-deployment.json及runtime-verified.json。没有操作看板、前端、真实核销或Git提交推送。
