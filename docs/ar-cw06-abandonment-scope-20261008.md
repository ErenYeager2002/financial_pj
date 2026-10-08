# CW06 / F1：未发布结果封存的完整停止证明

2026-10-08 本轮已修改、部署并完成只读浏览器验收。该记录保存本轮事实，不改变业务授权，也不代表整个 Pi 施工方案完成。用户最新“继续”已恢复施工；此前暂停记录保留为历史。

## 判定与封存边界

封存未发布结果前，全部已启动的盈亏、流转 writer 及当前失败动作均须具有完整 Linux 后代执行域停止证明。只有直接父进程退出、部分后代、未知范围、缺失记录或身份漂移，均不得授权释放材料占用。证据动作 ID 集合必须精确覆盖上述动作，并以稳定摘要绑定原 action、workflow、attempt、Worker 和 process refs。

历史“已封存”的展示与安全解除分别判定。旧 marker 不改写；具备完整原事实的旧凭据可通过真实重验，只有 opaque 指纹或 direct-child 范围的凭据继续需要调查。新 v2 保存完整停止汇总和原证据身份摘要；读取时核验完整集合及当前身份，不把封存标记本身当作解锁证明。保留前序成功材料、失败与暂存证据、旧任务不能恢复的规则，不自动重跑核销。

## 验证证据

- 三次针对性负例先复现再修复：父退出但 setsid 子继续写入、停止汇总漏 writer、原 Worker / process refs 改变。
- 最终 52 项专项通过；真正 PostgreSQL 专项 1 项通过、0 项跳过。此前“6 passed, 1 skipped”来自导入的 SQLite 用例，唯一 PostgreSQL 用例被跳过，不能算作 PostgreSQL 验证；以本次真实 PostgreSQL 结果纠正该口径。
- Standards / Spec 双轴静态复审均无阻断项。生产候选构建通过，临时脚本与隔离测试资源按精确归属清理。
- 本轮未运行真实核销、恢复或调查操作，未修改业务工作簿或历史封存记录，未提交或推送。

## 已部署版本及回读

后端镜像：`sha256:cddc9fea86f0e81ee86170a73a47dbaf53c1a5ac13ae149160b2c72f9557dfd6`。

回滚目录：`/home/lee/financial-platform-isolated/releases/managed-20261008-001734-55c0fdd2`。回滚须保留本轮完整停止证明判断，不能恢复仅凭旧 marker 即解除占用的行为。

API、标准 Worker 和任务检查 Worker 的运行镜像一致，以下运行文件均与持久化源码匹配：

| 文件 | SHA-256 |
|---|---|
| backend/app/ar_abandon.py | 239f9d51e243adfbc2eebbb7708132783e5331a0e5093230695c3b8eafbd3339 |
| backend/app/ar_execution_safety.py | 003381ed4028bad3465269f12c3b26923bea3b1e308a2e5364e169030165f5dd |
| backend/app/ar_process_inspection.py | 3ca4d0bd195adb6057f76cf6bf3e1161e09c16fdb436e0696cfea91b251a97cb |

API 为 healthy；两个 Python Worker 为 running，没有 Docker Health 字段，不将 running 写成独立健康验收。前端镜像保持 `sha256:cfd960509a9e013af1d24f35e5ed0cd9d49cf639a30fe54cbdf6b57aca9f0c10`，本轮未改前端。维护模式 normal，部署后五项活动计数均为 0。独立 AR balance.37 发布保留。

## 历史数据与浏览器验收

三条历史 marker 原样保留，其中一条需要调查。当前已检查材料 scope 的 blocker 数为 0，仅说明这些 scope 当前没有阻断，不代表所有历史未知状态已清除，也不代表需要调查的旧任务已获解除。

实际浏览器选择 `6652c8cd…` 对应 2026-08-30 的日期任务；详细信息显示：

> 历史未发布结果已封存，但完整执行停止证明不足；材料占用仍须调查，不能据此新建冲突任务。

页面没有恢复或解锁按钮，GET 状态接口返回 200、`allowed=false`、`abandoned=true`、`needs_investigation=true`。页面导航控制台错误为 0。批次顶部原持久化 progress 仍显示历史封存消息，未重写历史记录。此次浏览器验收只读，未点击调查、核销或恢复。

## 施工进度

F1 本轮完成。整体施工仍未完成，继续 F2，随后处理 F4、F5、F3、G4、CW09、CW10、CW11；以各阶段实际验证与部署证据分别认定，不把本轮结果扩展为全项目完成或暂停。
