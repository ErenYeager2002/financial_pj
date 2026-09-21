# PR-04 已完成收尾步骤的撤权登记边界

2026-09-20：源码和线上生效均已核实，PR-04 整体仍未完成。

在完成脚本已成功退出、结果尚未登记期间发生账号停用、部门变更或 Skill 撤权时，允许平台登记已经完成的成果。必须具有当前租约、同动作/尝试/Worker/日期/Skill 的成功退出证据，并继续通过当前材料、发布证明、候选完整内容和复制后指纹校验。登记使用系统审计，同事务停止后续步骤及批次日期。此例外不授权启动脚本、领取任务或重新发布工作簿。

针对性 PostgreSQL 检查 67 项通过，包括两种执行模式、多日期停止、错误进程证据、失效租约与审计失败数据库回滚。静态 diff 检查通过；规格与规范两项只读审查未发现明确缺陷。候选和恢复镜像的迁移、事务及恢复策略检查通过。

与线上 b0c620c7f53c 的并行版本比较后保留 12 个 AR 文件改动。以该不可变镜像构建并上线 ba9fc73e6ff5；恢复镜像 ac187be08e2a 为受限 replay-only 策略，并非旧代码的完整业务恢复。部署前活动任务全为零。API、标准 Worker、发现 Worker 各核对 449 个后端及 AR 文件，全部匹配；运行用户 10001，数据库 f4b5c6d7e8f9，运行模式 normal，重启计数零。看板资源未修改。

证据文件：PR-04-completion-revocation-tests.json、candidate-check.json、recovery-check.json、preflight.json、deployment.json、runtime-verified.json 均使用本报告前缀；并行版本差异在 PR-04-completion-revocation-live-diff.json。

验证边界：测试构造进程日志，未覆盖真实核销子进程到登记的完整调用链，未执行真实财务核销。Pi 批次有其他正在运行动作时按现有规则等待退出，不能宣称立即取消所有动作。完成脚本启动前撤权的受控处理、完整执行矩阵和其他 PR-04 验收仍待完成；PR05–21 尚未完成。

## 真实子进程证据链补查

新增真实短 Python 子进程测试：父进程生成 prepared、started、exited 证据；进程退出后由独立数据库事务停用账号，再调用真实结果登记。成功退出可登记并停止后续执行；退出码 7 即使具有退出日志也拒绝登记。两个新用例通过，approval-authorization 合计 69 项通过，见 PR-04-completion-real-process-tests.json。此前构造日志测试继续保留。

测试仍替换 ArExecution 构造，仅验证真实进程证据到登记的连接；未运行完整业务 Skill 或真实核销。此次只增加远程测试和正式验证记录，运行代码未改变，不重启生产服务。

## PR-04 尚缺的授权观察证据

按执行指南 6.6 第 10 项检查，普通 Run 的 claim/start 使用 modules/execution/authorization.py 的 execution_owner(observe=True)，会记录授权事实摘要。Workflow 的 workflow_owner_context 当前只刷新身份和 Skill 权限，不记录观察摘要。AST 调用盘点和函数正文核实了此差异；这不是已经证明权限可绕过，而是完成标准中的可审计观察缺失。

后续应共用授权事实摘要实现，按实际锁保护的 claim/start/write/publish 边界记录 phase、workflow/action/attempt 和观察摘要，保持调用方事务所有权。不能把普通查询全部变成审计写入，也不能以任务历史角色生成摘要。需验证撤权拒绝、角色变更摘要变化、审计失败回滚和既有 403 接口兼容。安全收尾开始前的撤权处理及全入口矩阵仍待完成。
