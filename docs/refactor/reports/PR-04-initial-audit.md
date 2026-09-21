# PR-04 执行阶段授权初查

2026-09-20。仅源码检查，未修改执行政策、权限或业务数据；当前线上仍为已验证PR-03补丁。规格为execution-guide.md §6.6，后续需要覆盖create/confirm/start/read/write/publish/cancel并记录锁顺序。

| 入口 | 当前证据 | 下一项验证 |
| --- | --- | --- |
| 普通Worker领取与执行 | worker.claim_next_run校验快照与并发数；_execute_claimed_run直接构造finance_user，不读取当前User/权限 | 排队后停用、撤权、换部门、管理员降权的合成回归，再接统一边界 |
| 普通确认 | main.confirm检查传入UserContext的权限，confirm_run只改状态与步骤 | 锁内刷新身份，固定任务归属/材料/快照及确认条件 |
| 普通取消 | main.cancel通过get_run_or_404再取消，没有can_run门槛 | 保留撤权后合法取消，补当前身份及跨部门猜ID验证 |
| Workflow/AR | workflow_owner_context已读取当前User和部门，verify_input_binding每次script前/发布前调用 | 逐入口核对锁与授权顺序；保留不可逆步骤的回读与证据保存，不粗暴终止 |
| Native | require_native_skill先refresh再assert | 跟踪所有Agent/Native直接入口调用，避免只改HTTP |
| Pi环境 | operate持文件锁，start重检挂载Skill；stop/jobs.cancel跳过Skill检查 | 跳过Skill权限不能跳过当前身份；require_session当前只在check_skill且存在挂载时refresh，需要合成测试界定 |
| 管理权限变更 | update_department_user走_lock_admin_change；replace_user_permissions内部commit | 核对与执行检查一致的锁/CAS及授权观察记录，不新增第二套权限事实 |

尚未宣称全面检查完成或存在真实越权事件；以上Worker缺口由当前源码确定，其余列为需要验证的边界。PR-01历史全链离线迁移与PR-03浏览器验收继续保留，不因进入PR-04而从完整目标删除。
