# 财务平台 API 契约

FastAPI OpenAPI 是当前 Next.js 项目的唯一平台接口契约来源。不要在页面或 feature 中重新手写平台 DTO。

## 文件

- `../contracts/financial-platform.openapi.json`：从仓库根目录导出的唯一稳定快照。
- `src/features/platform-api/generated.ts`：由 `openapi-typescript` 生成，不手工修改。
- `src/features/platform-api/types.ts`：面向前端 feature 的稳定别名。

## 更新流程

先在 `D:\\BESTEASY\\financial_pj` 导出当前契约：

```powershell
.\\.venv\\Scripts\\python.exe scripts/export_openapi.py
```

再在 `web` 目录生成并检查 TypeScript 类型：

```powershell
pnpm contracts:generate
pnpm contracts:check
pnpm typecheck
```

前端不再维护一份独立的 `web/contracts` 副本，避免契约过期。

`TaskDraft` 和 `ApprovalRecord` 已冻结名称与字段，但对应数据库和执行流程仍属于后续阶段。前端在接口正式实现前不得用 Mock 触发任务或审批。
