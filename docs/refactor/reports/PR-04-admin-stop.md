# PR-04 停用账号的管理员代停入口

2026-09-20，已上线并完成运行回读。

新增POST /api/pi-runtime/admin/users/{owner_id}/sessions/{session_id}/stop。仅有效同部门管理员可停止已停用账号的指定Pi会话。目标用户和会话作用域由服务端核对；不构造原用户身份代授权，不接收任意运行操作。普通用户自己的操作仍经过原有账号/Skill检查。

等待会话锁不持global；取得会话锁及global后重新检查实际管理员、目标状态、部门和会话归属。先提交pi.session.admin_stop_requested审计，再释放global后向manager派发固定stop。确认running=false与environment_running=false才记pi.session.admin_stop；异常或未确认响应记pi.session.admin_stop_unknown。审计使用实际管理员和同一request_id，不把请求成功等同停止成功。不自动重试该操作。

本轮提取了纯会话目录归属与运行管理器传输函数，避免引入通用skip_auth标记。后台接口未新增管理UI按钮，不代表完整前端管理流程已验收。

## 验证

PostgreSQL权限专项48项通过；Pi文件传输2项通过。包括同部门合法代停、旧管理员降权、停用管理员、跨部门/其他会话、目标重新启用、等待会话锁时管理员降权、传输失败与未知审计、请求审计先提交和网络期间global可由另一连接获取。使用实际RuntimeManager.dispatch验证停止协议，但Docker与桥接I/O均替换为合成函数，未停止真实运行环境。

HTTP测试确认200及拒绝匿名请求；匿名测试替换认证依赖，只证明路由拒绝行为，不属于真实登录会话验收。响应AdminStopResult明确两个字段均为false。

OpenAPI已从当前应用完整导出，含本次新路由及之前遗漏的既有Pi/assistant/submission接口；没有删除路径。后端contracts --check、openapi-typescript --check以及当前src/tests的TypeScript检查通过。首次类型检查错误挂载了构建镜像历史测试，补用当前测试后通过，没有为此修改测试夹具。

Spec与Standards独立只读审查完成；最初指出的契约缺口已修复。候选f0c678e4861c及恢复b58f3b1e38ef通过隔离PG探针，恢复保留同一安全核心。运行代码仅新增pi_admin_session_service及修改pi_runtime_service/routers.pi_runtime；前端仅生成类型，无界面运行逻辑修改。

当前源码阶段、部署结果与上线读回分别以本记录、PR-04-admin-stop-deployment.json、PR-04-admin-stop-runtime-verified.json为准。PR-04剩余全入口/阶段授权观察、审批确认快照和写入资格矩阵仍须完成；完整PR00–PR21目标不变。没有停用真实账号、停止真实Pi会话、执行核销、提交或推送，看板未操作。

发布退出0，API和两个Worker各197个后端文件哈希一致，UID10001，重启次数0；新接口响应契约存在。DB仍f3，平台normal，五类活动任务计数0。未执行真实管理员停止请求。前端只有类型生成文件变化，TypeScript检查已通过，没有界面或运行代码变化，因此没有重启前端。
