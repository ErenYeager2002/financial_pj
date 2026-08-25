# 认证模式

平台支持 `session`、`clerk` 和 `hybrid` 三种认证模式。Next.js 与后端必须使用相同的 `FINANCIAL_AUTH_MODE`，平台角色、部门和 Skill 权限始终读取本地用户表。

## 本地会话模式

设置 `FINANCIAL_AUTH_MODE=session`。管理员在用户管理页创建用户并分配一次性初始密码；平台不提供公开注册。登录请求由 Next.js 的 `/api/auth/login` 转发到后端，浏览器只能收到 HTTP-only 会话 Cookie，前端代码不能读取会话令牌。

新用户首次登录后会进入 `/auth/change-password`。修改完成前，中间件会把业务页面请求转到改密页，后端同时拒绝业务接口。管理员禁用用户或执行“重置为一次性密码”后，已有会话立即失效。密码重置审计只记录操作人和目标用户，不记录密码。

生产环境使用本地会话时必须启用 HTTPS，并设置 `FINANCIAL_SESSION_COOKIE_SECURE=true`。

## Clerk 模式

切换前为每个需要登录的平台用户绑定唯一的 `clerk_user_id`，然后将认证模式改为 `clerk`。Clerk 只提供登录身份；角色、部门、账号状态和 Skill 权限仍由本地用户表决定。本地登录接口在该模式下关闭。

不要在生产环境启用 `FINANCIAL_DEV_CLERK_AUTO_PROVISION_ADMIN`。Clerk 模式启动时不会自动创建本地管理员；用户映射必须在切换前准备完成。原有 Clerk 登录、注册、用户资料和退出流程保持可用。

## Hybrid 模式

`hybrid` 同时接受 Clerk 身份和本地会话，只用于模式切换期间验证两条路径。完成迁移核验后应切换到 `session` 或 `clerk`，不能把 `hybrid` 作为长期日常配置。
