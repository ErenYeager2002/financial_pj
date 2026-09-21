# PR-04 普通工具输入快照检查

本轮基于远程持久化工作树，HEAD 6fce5bf1195c0591d8f8cfb53b84c32c0356f36d；未提交。对应 execution-guide.md PR-04 第5项输入归属、固定执行材料，以及第3项当前身份检查。本报告仅覆盖普通任务输入读取切片，不代表 PR-04 全部完成。

## 问题及实现

原 build_execution_request 只比较数据库 FileRecord.sha256 与当前源文件，没有与 Run.files_json 中提交时固定的 sha256 比较。文件和数据库同时变化、部门变化、复制期间变化、Session 缓存旧记录均可错误放行。旧 owner 严格相等检查还与创建阶段允许同部门管理员使用文件的规则不一致。

backend/app/adapters.py 现在在读取前按任务固定 owner/department 刷新真实身份和 Skill 权限，刷新文件记录；固定部门与 input 类型，复用 assert_owner 的当前身份规则；任务绑定哈希、数据库哈希、源文件及最终工作副本内容必须一致。缺失固定哈希的旧任务拒绝执行，不能用当前内容补成新基线。Python、RPA 和 HTTP 共用此入口，失败不生成 request.json、不启动执行器。不改变自动核销审批产品规则、不恢复旧双人审批流程。

所有检查发生在副作用启动之前；此处不承诺跨文件系统瞬时撤权，也不新增数据库提交或扩大事务锁。工作副本检查失败时保留尝试目录，由既有保留规则处理，不批量清理财务文件。

## 验证

- 新增12项合成输入用例，位于 backend/tests/test_execution_authorization.py。最初7项在旧实现复现4失败：content_and_record、department、copy_race、stale_record；既有所有者/类型拒绝及正常输入通过。
- 最终 PostgreSQL execution-authorization 专项60项通过，exit0。覆盖管理员同部门兼容、降权拒绝，以及真实 Python/RPA/HTTP 适配器在输入失败时 Popen/httpx.post 未调用。没有真实业务网络请求或财务文件。
- 最终 ordinary-e2e 专项4项通过，exit0；合成上传、Worker执行、下载。两项依赖库弃用警告继续存在。
- 两轴只读审查均无剩余确定发现；首次指出的创建/执行管理员规则不一致已修复，并纠正为原有问题。
- 候选及恢复镜像隔离 PostgreSQL 检查通过，详见 PR-04-input-binding-candidate-check.json 与 PR-04-input-binding-recovery-check.json。恢复镜像保留本轮安全检查，只允许已绑定回执重放，不开放新普通提交。
- git diff --check 针对本轮文件通过。未运行全仓测试，未声称基线失败清零。

## 发布及剩余范围

发布预检 normal、五类任务为0；托管 backend-schema 发布 exit0，恢复 normal；三个后端服务镜像6bc600a791f2，各197个源码文件哈希匹配，UID10001，DB唯一revision=f3a4b5c6d7e8，replay_only=false、restart0。依据 PR-04-input-binding-deployment.json 与 PR-04-input-binding-runtime-verified.json。前端无修改，不构建或重启前端；不操作看板项目。不提交推送、不执行真实核销或自动重试。

PR-04 尚需普通任务确认记录/快照和固定 Skill 校验、Workflow/AR/Agent 的全阶段矩阵及授权观察覆盖；requires_approval 字段观察不代表恢复旧审批策略或已完成审批门禁。PR-05至PR-21及综合验收仍保留完整目标。
