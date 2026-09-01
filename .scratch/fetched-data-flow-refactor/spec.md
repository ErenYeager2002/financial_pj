# 取数、快照与任务数据流改造

Status: planned

创建日期：2026-08-31
最近更新：2026-08-31
当前进度：0/8 阶段完成

## 文档用途

本文件是取数、快照、任务工作区和业务材料版本数据流改造的唯一进度记录。实施人员开始或完成一个阶段时，必须同步更新本文件中的状态、日期和验证证据。

全部改造完成且满足末尾删除条件后，删除本文件；目录为空时同时删除 `.scratch/fetched-data-flow-refactor/`。不要长期保留已经完成的临时改造文档。

## 改造目标

1. 明确区分原始取数包、取数预览、Skill 快照和业务材料版本。
2. 使用数据库约束表达取数包的生命周期，不再通过 `context_json.fetched_data.available` 推测多种状态。
3. 统一实时智云取数与本地快照回放的调用接口。
4. 拆分承担多种职责的 `prepare_worklist`，让动作名称与实际业务阶段一致。
5. 让 `material_set_id` 成为业务材料版本的权威引用，减少重复状态。
6. 将批次的共享只读数据与各核销日期的可变工作区分开，降低失败恢复时的相互影响。
7. 让原始取数清理、预览保留和快照回放遵循明确、可审计、可重试的策略。
8. 保持现有核销判定、写前校验、原子写入、回读校验、逐日串行和任务互斥规则不变。

## 不在本次范围内

- 不修改应收核销金额、父回款、交付额、核销额、挂账和拆分链的业务判定规则。
- 不修改智云字段口径和四类导出数据的业务含义。
- 不取消取数后的人工检查。
- 不允许批次日期并行写入业务工作簿。
- 不覆盖用户上传的原始文件。
- 不借本次改造清理工作区中的无关改动。
- 不在存在活动应收核销任务或批次时迁移、重启 Worker 或修改其工作区。

## 当前问题

### 1. 取数状态语义混合

`workflow.context_json.fetched_data` 同时记录原始文件是否存在、数据是否已经取回、是否经过人工确认、页面预览是否可用以及来源是否为快照。`available=true` 不能准确说明原始四件套是否仍然存在，也不能说明是否允许回放。

### 2. 成功预览与可回放快照混用

成功任务终态清理会删除工作区中的 `01_智云导出`，但保留数据库预览。历史任务仍可展示 AR 分组和摘要，却不一定具备回放所需的四份 Excel、摘要清单和 SHA-256。页面和接口需要明确区分历史预览与可回放取数包。

### 3. `prepare_worklist` 承担过多职责

第一次执行时，它复制业务材料、实时取数或复制快照并暂停等待确认；确认后第二次执行时，它复用工作区、分类、校验并生成日清。调用方必须理解 `review_status`、`workspace_state`、`resume_after_review` 等内部状态才能判断实际行为。

### 4. 文件引用存在多份来源

同一组业务材料可能同时出现在 `material_set_id`、`files_json`、`context_json` 和批次字段中。状态更新遗漏时，任务可能同时持有互相矛盾的材料版本和文件列表。

### 5. 批次共享可变工作区

批次的取数文件、财务表副本、台账和过程产出位于同一个共享工作区。虽然减少复制，但单日失败、重试和清理需要理解前后日期的全部文件状态，恢复范围较大。

### 6. 清理属于业务动作尾部副作用

终态清理在 Worker 动作结束流程内执行。文件系统临时故障可能影响任务结束；清理没有独立状态、重试次数和最后错误记录。

## 目标数据模型

### FetchedBundle

新增 `fetched_bundles` 表，表示一次经过校验的原始取数包。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 不透明 UUID；回放入口使用该标识，不再以来源任务 ID 充当快照 ID |
| `owner_id`、`department_id` | 所有者和部门隔离 |
| `skill_id` | 当前固定为 `ar-hexiao-daily`，保留扩展能力 |
| `source_workflow_id`、`source_batch_id` | 来源任务和批次审计引用 |
| `source_type` | `live` 或 `replay` |
| `manifest_version` | 取数摘要格式版本 |
| `state` | `creating`、`ready_for_review`、`confirmed`、`consumed`、`raw_purged`、`invalid` |
| `date_from`、`date_to` | 取数范围 |
| `dates_json` | 实际允许消费的明确日期集合 |
| `storage_key` | 相对于取数包存储根的受控键，不保存任意绝对路径 |
| `raw_available` | 原始四件套与摘要是否存在且完整 |
| `preview_available` | 数据库预览是否存在 |
| `replayable` | 当前部署策略和文件完整性是否允许回放 |
| `created_at`、`confirmed_at`、`consumed_at`、`purged_at` | 生命周期时间 |
| `retention_until` | 原始取数包最晚保留时间；空值只允许用于显式永久保留策略 |
| `last_error` | 脱敏后的生命周期错误摘要 |

约束：

- `raw_available=false` 时 `replayable` 必须为 false。
- `raw_purged` 状态下 `raw_available` 和 `replayable` 必须为 false。
- 同一来源任务、清单版本和日期集合不能重复登记同一个取数包。
- 所有查询必须带所有者范围；管理员不能借角色跨用户回放业务取数。

### FetchedBundleFile

新增 `fetched_bundle_files` 表，记录取数包成员，不保存业务行内容。

| 字段 | 说明 |
| --- | --- |
| `bundle_id` | 所属取数包 |
| `reconciliation_date` | 文件对应的核销日期 |
| `dataset` | `payments`、`orders`、`writeoffs`、`order_details` 或 `summary` |
| `relative_name` | 取数包目录内的安全相对文件名 |
| `sha256` | 文件内容哈希 |
| `size_bytes` | 文件大小 |

唯一约束：同一取数包、日期和数据集只能有一个当前成员。

### 取数预览关联

`workflow_fetched_data_previews` 增加 `bundle_id` 外键。预览继续按日期和文件版本保存 AR 分组，但必须能够追溯到产生它的取数包。原始文件清理后预览可以继续存在；此时 `preview_available=true`、`raw_available=false`、`replayable=false`。

### 工作流引用

`workflow_sessions` 增加可空 `fetched_bundle_id`。关键状态通过关系查询获得。`context_json` 只保留页面说明、步骤标签、错误摘要和兼容期数据，不再作为取数包生命周期的权威来源。

## 目标存储结构

```text
data/
├─ uploads/{owner_id}/{file_id}/
├─ fetched-bundles/{owner_id}/{bundle_id}/
│  ├─ manifest.json
│  ├─ 回款记录_YYYYMMDD.xlsx
│  ├─ 订单交付_YYYYMMDD.xlsx
│  ├─ 核销明细_YYYYMMDD.xlsx
│  ├─ 订单明细_YYYYMMDD.xlsx
│  └─ 取数摘要_YYYYMMDD.json
└─ workflows/{owner_id}/{workflow_id}/
   ├─ skill/
   ├─ actions/{action_id}/
   └─ workspaces/{reconciliation_date}/
      ├─ 01_智云导出/          只读引用或任务内副本
      ├─ 02_我的表副本/
      ├─ 03_台账/
      ├─ 03_写入暂存区/
      └─ 04_产出/
```

取数包必须先写入同一存储根下的临时目录，完成文件数量、摘要版本、日期、只读标记和 SHA-256 校验后再使用原子重命名发布。数据库只有在原子发布完成后才能把状态改为 `ready_for_review`。

## 目标模块与接口

新增深模块 `backend/app/fetched_bundle_service.py`，调用方只依赖以下接口：

```python
materialize_bundle(
    db,
    *,
    workflow,
    source: LiveFetchSource | ReplayFetchSource,
    dates: list[str],
) -> FetchedBundleResult

confirm_bundle(db, *, bundle_id: str, actor: UserContext) -> FetchedBundle

assert_bundle_consumable(
    db,
    *,
    bundle_id: str,
    owner_id: str,
    dates: list[str],
) -> FetchedBundle

finalize_bundle(db, *, bundle_id: str, outcome: str) -> None
```

`materialize_bundle` 内部负责目录边界、临时目录、文件清单、哈希、原子发布和数据库状态。调用方不接触绝对存储路径。

建立取数来源接口：

```python
class FetchSource(Protocol):
    def export(self, dates: list[str], target: Path) -> FetchManifest: ...
```

实现两个适配器：

- `LiveZhiyunFetchAdapter`：解析受控凭据，通过现有网络策略只读访问智云。
- `SnapshotReplayAdapter`：根据 `FetchedBundle.id` 读取来源包，重新校验所有成员 SHA-256 后复制。

测试使用临时文件系统适配器，不通过真实智云或真实业务目录。

## 目标任务流

动作名称调整为：

```text
prepare_workspace
      ↓
fetch_data
      ↓
build_fetch_preview
      ↓
awaiting_fetched_data_confirmation
      ↓ 人工确认
build_reconciliation_plan
      ↓
apply_material_update
      ↓
finalize_batch（仅批次最后一天）
```

### `prepare_workspace`

- 固定并验证 `material_set_id`。
- 根据材料版本读取成员文件和 SHA-256。
- 创建日期级工作区。
- 把材料复制到 `02_我的表副本`。
- 写入 `workspace_state=ready`；失败时只删除本动作创建的临时目录。

### `fetch_data`

- 实时模式调用 `LiveZhiyunFetchAdapter`。
- 回放模式调用 `SnapshotReplayAdapter`。
- 生成并发布 `FetchedBundle`。
- 不执行分类、核销判断或业务工作簿写入。

### `build_fetch_preview`

- 从已经发布且哈希一致的取数包解析 AR 分组。
- 以 `bundle_id + reconciliation_date + revision` 保证幂等。
- 完成后设置 `preview_available=true`。
- 任务进入 `awaiting_fetched_data_confirmation`。

### 人工确认

- 确认接口锁定取数包记录并检查当前状态。
- 记录确认人和确认时间。
- 原子更新取数包为 `confirmed`，并创建唯一 `build_reconciliation_plan` 动作。
- 重复确认返回现有动作，不创建重复任务。
- 回放取数不能连接智云补取；实时取数仍沿用现有补取和再次确认规则。

### `build_reconciliation_plan`

- 只消费已确认取数包。
- 校验任务日期属于取数包明确日期集合。
- 将所需日期文件复制或只读映射到日期工作区。
- 执行现有分类、日清生成、写前校验和计划生成。
- 不改变任何金额和挂账业务规则。

### `apply_material_update`

- 使用日期工作区的写入暂存区。
- 执行现有写前指纹、原子替换、逐格回读和写后幂等校验。
- 成功后登记输出平台文件并发布新的 `WorkflowMaterialSet`。
- `material_set_id` 是后续日期唯一权威输入；`files_json` 只保留非材料临时文件或兼容期派生值。

## 批次数据流改造

1. 批次创建时仍一次建立所有日期任务，只有第一天进入运行。
2. 批次只生成一个共享、不可变的 `FetchedBundle`，包含明确选择日期的数据。
3. 每个日期使用独立工作区，不能直接修改共享取数包。
4. 第 N 天成功后发布材料版本 N，并把 `material_set_id` 传给第 N+1 天。
5. 下一天从材料版本表读取文件，不从前一天 `context_json.next_files` 推测。
6. 当天失败只保留当天工作区和动作证据；未开始日期不创建可变工作区。
7. 重试从失败日期重新创建日期工作区，复用仍完整且允许消费的取数包和当前批次材料版本。
8. 最后一天完成后生成范围报告，再将批次置为成功。

## 保留与清理策略

### 默认策略

- 生产环境默认立即清理成功任务的原始取数包，保持当前隐私和存储边界；数据库预览继续保留。
- 开发和测试环境可以显式设置原始取数包保留天数，以支持离线回放测试。
- 只有 `raw_available=true`、`replayable=true` 且未超过 `retention_until` 的取数包出现在回放列表。
- 页面把原始文件已经清理的记录显示为历史取数预览，不显示为可回放快照。
- 失败、取消和未确认的取数包在确认没有活动动作引用后清理原始文件和未完成预览。

新增配置：

```text
FINANCIAL_FETCH_BUNDLE_RETENTION_DAYS
```

生产默认值为 `0`；开发和测试必须显式配置非零值。配置变化只影响新取数包，不追溯延长已经到期的数据。

### 清理动作

新增独立、幂等的 `purge_fetched_bundle` 动作或后台清理任务：

- 先把状态改为待清理并提交数据库。
- 删除受控取数包目录。
- 删除成功后设置 `raw_purged`、`raw_available=false`、`replayable=false` 和 `purged_at`。
- 文件已不存在视为幂等成功。
- 删除失败记录脱敏错误和重试次数，不改变业务任务的成功状态。
- 清理前再次检查是否存在活动任务或动作引用。

## 兼容和迁移

1. 新增数据库迁移、SQLAlchemy 模型、Pydantic 契约和 OpenAPI 类型。
2. 旧任务存在持久预览但没有原始四件套时，迁移为 `raw_purged`，关联现有预览，禁止回放。
3. 旧任务仍有完整取数目录时，只在受控迁移命令显式执行时校验并登记；不得在数据库迁移中广泛扫描磁盘。
4. 兼容期继续接受 `snapshot_workflow_id`，服务端将其解析为唯一有效 `bundle_id`；响应同时返回废弃提示。
5. 前端和调用方全部改用 `fetched_bundle_id` 后，删除 `snapshot_workflow_id` 兼容字段。
6. 旧 `context_json.fetched_data` 保留只读兼容解析；新任务不再写入生命周期权威状态。
7. 迁移命令必须支持 `--dry-run`、所有者范围、数量摘要和写后回读，不输出客户、订单、回款编号或绝对业务路径。

## 安全与审计

- 取数包目录继续按用户隔离；所有文件访问都校验路径位于配置存储根内。
- 拒绝符号链接、绝对成员路径、路径穿越、缺失文件、额外未知文件和哈希不一致。
- 回放只允许原所有者，不因管理员角色扩大到其他用户。
- 智云凭据只在实时取数适配器进程内短暂存在，不写入取数包、数据库、命令行、环境变量或日志。
- 审计只保存取数包 ID、任务 ID、日期数量、数据集数量、状态、耗时和结果，不保存业务编号与金额明细。
- 补取后必须产生新 revision；旧 revision 保留审计引用，不作为当前预览返回。
- 实施数据库迁移、清理和部署前，必须只读检查活动 `WorkflowBatch`、`WorkflowSession` 和 `WorkflowAction`。

## 测试矩阵

每个阶段只在相应测试变红后实现，并在完成时记录验证命令和结果。

| 维度 | 必测场景 |
| --- | --- |
| 来源 | 实时取数、快照回放 |
| 入口 | 单日、多日批次、整月、非连续日期 |
| 内容 | 正常四件套、缺文件、多文件、旧清单版本、文件篡改、摘要日期错误 |
| 状态 | 创建中、等待确认、已确认、已消费、已清理、无效 |
| 终态 | 成功、失败、取消、超时、Worker 租约恢复 |
| 人工操作 | 重复确认、补取后再次确认、确认与取消并发 |
| 批次 | 一次取数、日期串行、空日期、单日失败、失败日期重试、范围报告失败 |
| 材料 | 当前版本、版本冲突、前一天发布后传递、写后回读失败 |
| 清理 | 文件存在、文件已不存在、删除失败重试、活动引用阻止清理 |
| 权限 | 跨用户读取、跨用户回放、非法路径和符号链接 |
| 前端 | 历史预览与可回放快照文案、状态展示、加载和错误状态 |

完整验证至少包括：

- 新模块接口测试和临时文件系统集成测试。
- 工作流、批次、取数预览、快照回放、材料版本和清理回归。
- Alembic 升级与降级测试，升级后数据回读。
- OpenAPI 导出检查、后端 Ruff、前端类型检查、lint 和生产构建。
- 开发端单日与多日合成数据验收；不得用真实业务数据进行首次迁移验收。
- 部署前后数据库状态、文件数量和 SHA-256 摘要回读。

## 实施阶段与进度

状态只使用 `pending`、`in_progress`、`blocked`、`completed`、`verified`。一个阶段只有在代码、迁移、测试和本阶段文档更新全部完成后才能标记 `completed`；开发端实际回读通过后标记 `verified`。

| 阶段 | 状态 | 实施内容 | 完成证据 | 最近更新 |
| --- | --- | --- | --- | --- |
| 01 基线与决策 | pending | 固定现有生命周期测试；确认保留策略；新增 ADR；记录现有数据库和目录契约 | 待填写 | 2026-08-31 |
| 02 取数包模型 | pending | 增加 `FetchedBundle`、成员表、外键、约束、迁移和契约 | 待填写 | 2026-08-31 |
| 03 深模块与来源适配器 | pending | 实现取数包原子发布、实时取数和回放适配器、完整性校验 | 待填写 | 2026-08-31 |
| 04 动作拆分 | pending | 拆分工作区、取数、预览、计划和写入动作；迁移状态机与恢复逻辑 | 待填写 | 2026-08-31 |
| 05 材料版本唯一来源 | pending | 以 `material_set_id` 为权威，删除新流程中的重复材料状态 | 待填写 | 2026-08-31 |
| 06 批次日期工作区隔离 | pending | 共享不可变取数包，建立日期独立工作区，只传递材料版本 | 待填写 | 2026-08-31 |
| 07 保留清理与前端 | pending | 幂等清理、保留配置、历史预览与回放入口区分、兼容迁移 | 待填写 | 2026-08-31 |
| 08 全量验证与开发端同步 | pending | 完整测试矩阵、合成数据验收、开发端部署与读回、最终复查 | 待填写 | 2026-08-31 |

## 进度更新格式

阶段有变化时，在上表更新状态，并在此处追加记录：

```text
### YYYY-MM-DD · 阶段 NN

- 状态：in_progress / blocked / completed / verified
- 修改：文件和行为范围
- 迁移：数据库或存储变化；无则写无
- 验证：执行命令、通过数量和已知警告
- 开发端：未同步 / 已同步；地址和凭据不写入文档
- 剩余：下一项具体工作或阻断条件
```

### 2026-08-31 · 建立改造文档

- 状态：planned
- 修改：只创建本规格与进度文件，没有修改代码、数据库、文件存储或运行服务。
- 迁移：无。
- 验证：对照当前模型、工作流、取数预览、快照回放、材料版本和批次代码建立实施范围。
- 开发端：未同步，本阶段没有运行时代码变化。
- 剩余：从阶段 01 开始，先建立现有行为基线和生命周期 ADR。

## 每阶段实施规则

1. 开始前检查工作树和活动批次，保留无关修改。
2. 把当前阶段状态改为 `in_progress` 后再修改代码。
3. 先增加会失败的接口级或状态机测试，再实现最小行为。
4. 数据库和文件系统变化必须具备失败恢复与幂等测试。
5. 只运行合成数据或明确隔离的快照；未经用户明确要求不得运行真实核销。
6. 一个阶段完成后执行针对性检查，并把结果写回本文件。
7. 涉及数据库迁移、Worker 或开发端同步时，先确认没有活动业务动作。
8. 每阶段只提交该阶段相关文件，不混入工作区已有修改。
9. 最后阶段执行 Standards 与 Spec 两轴代码复查；发现问题回到对应阶段处理。

## 完成条件

以下条件必须全部满足：

- [ ] 八个阶段全部标记为 `verified`。
- [ ] 取数包、预览、回放、任务工作区和材料版本的术语与 `CONTEXT.md` 一致。
- [ ] 新旧数据库迁移和必要兼容路径验证通过。
- [ ] 实时取数与快照回放通过同一深模块接口进入任务流。
- [ ] `prepare_worklist` 不再同时承担取数前和确认后的两套行为。
- [ ] 新任务不再依赖 `context_json.fetched_data.available` 判断原始文件、预览和回放状态。
- [ ] 批次共享取数包只读，各日期工作区相互隔离。
- [ ] 材料版本传递以 `material_set_id` 为权威来源。
- [ ] 清理任务幂等，清理失败不改变已成功的财务任务状态。
- [ ] 历史取数预览和可回放快照在接口与页面上明确区分。
- [ ] 后端完整测试、Ruff、迁移、OpenAPI、前端测试、类型检查、lint 和生产构建通过。
- [ ] 使用合成数据完成单日、多日和失败恢复验收。
- [ ] 开发端完成部署或源码同步，数据库、Worker、页面和文件状态读回一致。
- [ ] Standards 与 Spec 代码复查无未处理问题。
- [ ] 没有活动迁移、临时兼容任务或必须依赖本文件才能理解的未完成操作。

## 删除条件

完成条件全部勾选后执行最后一次只读检查：

1. 确认本文件中的所有阶段均为 `verified`，完成证据可由代码、迁移、测试和审计事实独立复现。
2. 确认需要长期保留的领域术语已经写入 `CONTEXT.md`，硬性架构决策已经写入 ADR；不要把本文件复制成另一份长期进度文档。
3. 确认 `.scratch/fetched-data-flow-refactor/` 下没有未完成问题单或恢复说明。
4. 删除 `.scratch/fetched-data-flow-refactor/spec.md`；目录为空时删除该目录。
5. 删除操作只删除上述临时文档和空目录，不删除代码、测试、迁移、ADR、业务数据、快照或审计记录。
