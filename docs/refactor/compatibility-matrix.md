# 兼容性验收矩阵

此表保留初始兼容面及尚未完成项；后续已验证切片见文末。静态入口存在不能证明请求和历史数据兼容，历史基线描述不代表最新部署状态。

| 兼容面 | 当前依据 | 后续阶段 | 当前证据与缺项 |
| --- | --- | --- | --- |
| HTTP 请求和响应 | contracts/financial-platform.openapi.json、后端 schemas、前端 generated.ts | PR-07/16 | 前端 contracts:check 通过；后端 frozen version 测试期望旧字符串，需核查差异 |
| 材料版本与历史链 | CONTEXT.md Workflow Material Set；既有 workflow/material 服务 | PR-09/12/14 | 当前工作簿与 DB 迁移兼容尚未验收，禁止通过修改生产材料取巧 |
| Workflow/Pi 固定执行方式 | ADR 0003 | PR-08 至 13 | 不自动切换或失败回退；执行路径改造尚未开始 |
| Native Skill 运行与成果 | ADR 0006 | PR-13/14/18 | 活跃 systemd sandbox 已确认；历史命令/成果兼容尚未验收 |
| 文件引用与保留 | deployment/file_retention_guard.sql | PR-14 | 10 项专用 PostgreSQL 测试通过，仅覆盖文件保留 SQL，非完整成果契约 |
| Schema 新旧应用兼容 | migration-ledger.md | PR-01/21 | 30 个迁移静态盘点完成；未运行升级/降级/旧应用验证 |
| 前端导航与历史链接 | web/tests/platform-navigation.test.ts、App Router 路径 | PR-16 | 基线导航 3 项失败，需核对当前产品入口，不直接删断言 |
| 完整重建 | scripts/refactor/Dockerfile.frontend-test；web/Dockerfile.monorepo | PR-17 | 已发现旧 builder 缺本地 Agent runtime，正在重新构建依赖，未证明完整发布可重建 |

缺少运行证据的项均未通过。原方案全部测试和最终门禁仍以 test-matrix.md 及 execution-guide.md 为准。


## 已验证的 PR-04 切片与剩余项（2026-09-20）

| 兼容面 | 已验证证据 | 仍未证明 |
| --- | --- | --- |
| 普通执行快照 | PR-04-execution-snapshot-runtime-verified.json；新记录原子创建、旧绑定回执恢复，255 项权限/快照及19项提交相关测试 | 未覆盖完整 Workflow/AR/Pi 全阶段输入与授权契约 |
| PostgreSQL f4 新表 | 普通执行快照候选与恢复镜像迁移、重复迁移、只读运行角色；实际 DB f4 回读 | 不能将旧 f3 应用直接当成 f4 回滚版本；全历史离线迁移仍有已知缺项 |
| 审批身份与并发 | PR-04-approval-authorization-tests.json，24 项专用PG用例，锁等待与并发/回滚 | 合成证据不能代替真实财务回读；审批申请入口及发布观察矩阵仍待核对 |

后续运行以对应 runtime-verified.json 为准。这里不把 PR-04 局部检查标成阶段全部完成。
