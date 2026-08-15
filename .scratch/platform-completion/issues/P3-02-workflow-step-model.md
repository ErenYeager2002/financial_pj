# P3-02 步骤级工作流模型

状态：已完成

负责人：后端并行任务

阻塞：无

## 交付

- 新增 WorkflowDefinition、StepDefinition、StepRun、ArtifactBinding 和 ApprovalBinding。
- 新增 Alembic 迁移及必要索引、外键和唯一约束。
- 保持现有 Run、WorkflowSession 和 Worker 行为兼容。
- 增加模型、迁移和跨用户资源隔离测试。

## 验收证据

- Alembic 可从当前 head 升级。
- 定向测试与 Ruff 通过。
- 未改变现有任务创建和执行接口。

## 实施记录

- 新增 Alembic revision `c82f4e719ab3` 和加固 revision `e91b7c4a2d30`；后续 P3-05 迁移后生产 PostgreSQL 当前 revision 为 `c5d9f3a8201b`。
- 新增五类 ORM 模型、受控步骤类型、必要外键、唯一约束、检查约束和查询索引。
- 模型/迁移、资源隔离、审批、API 契约、标准任务、工作流和多 Worker 定向回归通过。
- P3-02 改动范围 Ruff 通过；未修改 Next.js 前端或现有任务执行接口。

## 双轴审查修复记录

- 为 Run、WorkflowSession、FileRecord、ApprovalRecord 及步骤资源增加作用域唯一键，并以复合外键阻止 StepRun、ArtifactBinding、ApprovalBinding 跨 owner/department 错绑；SQLite 模型行为测试和迁移结构检查通过。
- 非幂等步骤被数据库约束为 `max_attempts = 1` 且 `retryable = false`；工作流状态、步骤风险等级、Worker 池和步骤执行状态均改为受控集合。
- ArtifactBinding 与 ApprovalBinding 采用 insert-only 语义：ORM 事件与 SQLite/PostgreSQL 触发器共同拒绝更新、删除和替换。
- 新增旧标准任务、旧工作流动作和旧任务步骤 API 兼容测试；领取前无需已有 StepRun。P3-03 若在领取时补建步骤，不影响旧任务被领取。
- 验证：`test_workflow_step_models.py` 23 项通过，`test_database_migrations.py` 5 项通过，限定 4 个 Python 文件 Ruff 通过；P3-03 并行变更后的旧标准任务 Worker 兼容测试单独复核通过。
- 生产 PostgreSQL 原生 SQL 完整性检查通过；6 个并发领取者仅 1 个成功领取，剩余 5 个保持排队。
- 标准任务工作流定义改为 PostgreSQL/SQLite 原子 upsert，避免并发首次创建时返回唯一约束错误。
- 后端全量测试和 Ruff 已通过；Windows pytest 结束时仅有既有临时目录清理权限提示，进程退出码为 0。
