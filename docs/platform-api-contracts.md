# 财务平台 API 契约

FastAPI OpenAPI 是当前 Next.js 项目的唯一平台接口契约来源。不要在页面或 feature 中重新手写平台 DTO。

## 文件

- `contracts/financial-platform.openapi.json`：从 `financial_pj` 导出的稳定快照。
- `src/features/platform-api/generated.ts`：由 `openapi-typescript` 生成，不手工修改。
- `src/features/platform-api/types.ts`：面向前端 feature 的稳定别名。

## 更新流程

先在 `D:\BESTEASY\financial_pj` 导出当前契约：

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
.\.venv\Scripts\python.exe scripts\export_openapi.py `
  --output D:\anything\next-shadcn-dashboard-starter\contracts\financial-platform.openapi.json
```

再在当前项目生成并检查 TypeScript 类型：

```powershell
pnpm contracts:generate
pnpm contracts:check
pnpm typecheck
```

`TaskDraft` 和 `ApprovalRecord` 已冻结名称与字段，但对应数据库和执行流程仍属于后续阶段。前端在接口正式实现前不得用 Mock 触发任务或审批。
