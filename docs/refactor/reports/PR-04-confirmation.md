# PR-04 普通 Worker 确认必要条件

基于远程持久化 worktree，HEAD 6fce5bf1195c0591d8f8cfb53b84c32c0356f36d，未提交。PR-04第5项切片，完整方案范围不变。

## 修改

新增 backend/app/modules/execution/preconditions.py，在 Worker 领取和启动时校验 Run.confirmation_required 与固定 manifest.risk.requires_confirmation 一致；需要确认时 confirmed_by 非空且 confirmed_at 存在。缺少证据或标志不一致时按 CONFIRMATION_INVALID 记录失败，不运行适配器，不增加领取前的attempt。调用复用调度global锁，启动复用任务fence行锁；启动时的manifest解析移动到刷新任务之后。Worker领取也刷新可能缓存的Run。

这不是双人审批，不改变产品现行免审批流程；过去确认人的当前角色不被伪造，也不作为替代任务所有者当前权限的依据。此检查仅证明确认记录必要条件，未证明完整确认载荷/参数/Skill目录内容固定，不能标记完整PR-04已验收。

## 验证

新增 test_confirmation_is_required_at_claim_and_start 10项真实隔离PostgreSQL参数用例。旧实现8失败，分别为领取/启动时missing_actor、missing_time、missing_both、flag_disabled；两个合法确认用例通过。修复后execution-authorization总70项通过，exit0；ordinary-e2e合成上传-执行-下载4项通过，exit0。两轴静态审查未发现确定剩余问题；git diff --check通过。候选/恢复镜像的隔离迁移、事务及受限恢复检查通过，见PR-04-confirmation-*-check.json。无真实财务调用或写入。

## 发布尚未完成：发现并行发布

候选e8be669f5ae6与恢复4186142473f9基于上一轮6bc600a791f2构建。预检退出1：Gateway did not confirm maintenance state。本轮没有执行--apply。

2026-09-20 05:17 UTC只读观察：另一项发布已经将三个财务后端切到ccf155fe9ee6，标签ar-allocation-contract-20260920，mode仍为full、五类活动任务为0。其Dockerfile只覆盖/app/skills；后端app所有Python文件哈希与上一轮输入检查版本一致。source-hashes.json列出正式版和实验版AR Skill共10项分配契约相关文件变化。因此旧候选不可直接发布，否则会回退该并行业务更新。发布对象必须改为继承并核验新Skill内容的镜像；不得因临时未识别维护进程而强制normal或覆盖服务。

已向用户询问是否另一个会话正在发布；等待协调期间可继续独立源码/测试检查，不能宣称确认检查线上已生效。没有操作看板、没有Git提交推送、没有真实核销。

## 下一步

重新核实并行发布的完成状态及新Skill哈希，保留其变更后构建候选与兼容恢复镜像，再空闲门禁、安全发布和运行回读。之后继续完整确认快照、Skill目录校验及Workflow/AR/Agent全阶段矩阵。PR-05至PR-21仍未完成。

## 用户确认后的合并

用户明确要求保留另一会话更新并合并本轮改动。已将该发布的10项AR Skill文件同步到本远程持久化工作树；修改前逐项比较前一运行镜像，两个字节差异仅为换行，文本无独立变化，其余无冲突。记录见PR-04-confirmation-ar-merge.json。

基于ccf155fe9ee6构建合并候选e8ea15dac0ad与恢复2cb757b77426；候选及恢复镜像中的10项Skill文件全部匹配并行发布SHA-256，隔离PG/事务验证通过，详见PR-04-confirmation-merged-candidate-check.json及recovery-check.json。源码检查70项、普通E2E4项结果仍对应本轮相同后端代码。

合并后预检依然退出1：维护磁盘状态及公开状态均为full，托管入口要求正常状态起步；不应将其误报成网关不通。没有执行apply，没有强制改变另一会话维护状态或重启其服务。合并候选已准备完成，本轮确认检查仍未上线，需待并行发布归还正常状态后重新预检与安全切换。

## 合并发布完成

确认检查已随PR-04固定Skill快照切片发布；最终候选eb9577118d16基于另一会话最终d48bf2b825bc，205个AR文件哈希原样保留。发布exit0、mode/public normal，三个服务运行回读通过。详见PR-04-skill-snapshot.md和PR-04-snapshot-runtime-verified.json。上文未上线/维护阻塞是当时历史状态。
