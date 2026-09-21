# PR-04 核销脚本原子步骤与撤权边界

2026-09-20。此次只新增合成回归和正式验证记录，运行源码没有修改，不需要重启服务。当前候选清单对全部后端源码重新核对无差异，线上仍为a327561ba911。

## 验证证据

backend/tests/test_execution_authorization.py::test_ar_started_script_finishes_readback_but_next_script_is_denied，参数revoked、disabled、demoted，使用独立PostgreSQL用户、权限、材料版本、Workflow和Action。调用真实ArExecution.script、lock_execution、verify_input_binding和run_recorded_script，运行合成子进程；子进程只写临时标志和合成文本，没有工作簿或外部财务连接。

子进程先写合成结果并发出started信号；另一个数据库会话完成撤权后释放等待。原进程继续回读，返回0，并保存prepared/started/exited证据。随后同一执行对象的下一脚本在启动前被403拒绝，没有第二次执行记录。正式发布入口也被403拒绝，发布函数没有调用，材料版本仍为1。

执行命令：python3 -B scripts/refactor/postgres_baseline.py --suite execution-authorization。最终37项通过（含上述三参数及发布拒绝断言），20.33秒；静态git diff --check通过。隔离容器与数据库由测试入口清理。

## 结论范围

现有脚本调用边界已经满足不粗暴中止已开始子进程、阻止撤权后新脚本和发布的要求，此处无需再增加权限绕过分支。真实write_ledger要求writer返回ledger_verified=true；详细脚本内部读写时序仍需按固定业务快照另行核实。

本测试通过__new__隔离ArExecution的脚本边界，没有覆盖完整工作簿构造、暂存指纹、真实核销算法、整批恢复，不能代替完整核销E2E。发布测试只替换工作簿暂存入口与指纹前置检查，身份/租约/当前材料查询使用真实代码；最终报告哈希使用真实文件。测试撤权直接提交合成DB，不代表管理员接口并发锁的专项验收。

Spec与Standards独立只读审查认可上述有限结论，无确定问题；审查员未运行测试；不将其作为PR-04整体完成。尚需管理员代停、全入口授权观察与共享锁/CAS覆盖、真实固定脚本的安全回读界定及其余阶段验收。完整PR00–PR21范围不变。
