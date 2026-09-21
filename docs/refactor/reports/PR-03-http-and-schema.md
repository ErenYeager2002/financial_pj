# PR-03 HTTP 与数据库验证（2026-09-20）

状态：远程持久化源码已修改，未部署；PR-02/PR-03 兼容回退与正式构建尚未完成。未提交或推送；没有真实核销、业务材料写入、看板平台操作。

普通任务 BFF 改为调用 `/api/runs?standard_only=true`，后端对新建、准备恢复、最终持久化和已绑定重放检查固定清单是否 published、非 workflow、只读且不改输入。当前身份与工具权限每阶段重新检查。BFF 不再用最新目录拦截旧固定版本的重放。OpenAPI 仅更新本次新增 query 参数，并重生成 TypeScript；历史 OpenAPI 差异仍见 openapi-baseline-delta.json，未宣称整体契约一致。

缺少新 receipt 的历史普通 key 如果在同 owner/department 下已存在，返回 LEGACY_SUBMISSION_UNVERIFIED，不创建新任务，也不选择历史组第一条作为正确任务；Native 会话 key 不参与该检查。新请求继续使用独立强幂等 receipt。旧记录未修改。

## 验证

- prepared-payload：13 项通过，覆盖标准入口固定清单限制及准备数据白名单。
- PostgreSQL 实际 HTTP 端到端：4 项通过。包含正常与反序列化准备两种方式，分别顺序与 20 个并发客户端提交；第一次同时请求仅一次 prepare、同一任务 ID，20 个重放返回同一 ID。包含同 key 异参 409、禁用最新 registry 查找后的原版本重放、历史 key 拒绝、Worker 执行和结果文件下载。
- PostgreSQL HTTP 测试显式断言 engine dialect。首次试跑发现 conftest 覆盖回 SQLite，已修正并重新验证，之前试跑不计 PostgreSQL 证据。测试只能经隔离标记、测试库名称与本地地址校验启用；无生产网络、端口或数据挂载。
- schema-check：25 项通过。旧 f1/f2 被新应用拒绝，f3 缺少租约、Native 命令列、提交 token 或准备 payload 列也拒绝；只读启动不修表、不 stamp。
- 前端提交/草稿/错误透传：9 项通过；本轮接口修改后的 TypeScript 检查通过。
- 只读发布检查：normal，runs/batches/actions/discovery/assistant 均 0。

尚需最终审查、完整前端构建与浏览器验收、镜像内回归、兼容回退、正式迁移与 Native 分批回填及运行哈希核验。PR-04 至 PR-21 尚未开始，完整目标范围不变。

## 后续审查修正

PR-03-review.md 记录草稿 content_revision、固定版本恢复、浏览器 ready 恢复及数值类型比较修正；409 响应契约已补齐三个入口，不再只有 query 变更。当前 PostgreSQL 草稿专项5项、浏览器草稿4项通过。后端候选已构建并完成194文件hash、UID、schema及事务镜像验证；未发布。
