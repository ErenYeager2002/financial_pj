# 财务 Skill 平台架构

## 设计原则

- 大模型负责理解自然语言、补全受限参数和解释结果。
- Skill 负责财务计算、Excel 修改、RPA 和内部 API 调用。
- 用户每次运行都绑定 Skill 版本、内容哈希和只读快照，避免代码更新污染历史任务。
- 普通员工可运行已发布 Skill；只有 `skill_admin` 可维护和发布 Skill。
- 写入 ERP、提交凭证、发送外部邮件等动作必须由 Skill 声明风险并在执行前确认。

## 完整业务流程

```mermaid
flowchart TD
    subgraph P["Skill 开发与发布"]
        P1["开发者维护 SKILL.md、tool.yaml、脚本"] --> P2["代码评审与自动测试"]
        P2 --> P3["发布不可变版本"]
        P3 --> P4["平台 Registry 扫描并校验"]
    end

    subgraph U["财务员工使用"]
        U1["选择已发布 Skill"] --> U2["上传文件并描述要求"]
        U2 --> U3{"一次性或对话式"}
        U3 -->|"一次性"| UP["模型只对当前 Skill 提取参数"]
        U3 -->|"对话式"| UC["模型从阶段白名单选择动作"]
        UC --> UG["后端状态机校验人工确认硬闸"]
        UP --> U5["员工检查参数、文件或阶段产物"]
        UG --> U5
    end

    P4 --> U1
    U5 --> V["后端校验权限、Schema、文件归属、容差和幂等键"]
    V --> S["保存 Skill 版本、哈希与运行快照"]
    S --> R{"是否需要确认"}
    R -->|"是"| C["员工确认具体动作"]
    R -->|"否"| Q["进入任务队列"]
    C --> Q

    Q --> W{"选择隔离 Worker"}
    W --> WP["Python Worker"]
    W --> WR["RPA Worker"]
    W --> WH["HTTP Worker"]
    W --> WW["Workflow Worker"]
    WP --> E["确定性 Skill 执行"]
    WR --> E
    WH --> E
    WW --> E
    E --> O["输出统一 result.json 与结果文件"]
    O --> J["JSON Schema 校验、文件登记、哈希留存"]
    J --> L["SSE 实时进度与下载"]
    L --> H{"是否需要人工复核"}
    H -->|"通过"| A["归档运行记录和审计信息"]
    H -->|"退回"| F["反馈规则或数据问题"]
    F --> P1
    H -->|"无需复核"| A
```

## 运行状态

```text
waiting_confirmation
        ↓
      queued → running → waiting_user_action → running
                    └──→ succeeded / failed / timed_out / cancelled
```

## 当前实现

- FastAPI：接口、权限、文件、任务与 SSE。
- SQLite：第一期运行记录、文件元数据和事件；生产可切 PostgreSQL。
- 独立 Worker：按 `python`、`rpa`、`http`、`workflow` 池分别启动多个进程并轮询
  数据库队列。领取阶段由数据库全局调度锁串行化，执行阶段并行。
- 对话式执行器：会话、消息和动作独立留痕；状态机限制每阶段可调用动作，
  耗时动作由 `workflow` Worker 执行。
- 多日期批次：`WorkflowBatch` 保存日期集合和整体状态，每个日期仍对应一个
  `WorkflowSession`。同一批次严格串行；成功子任务输出的两份工作副本通过受控
  `FileRecord` 绑定传递给下一日。失败时不启动后续日期，准备阶段失败可从该日期继续。
- 并发控制：任务快照保存 `runtime.concurrency_limit`，Worker 领取前统计同 Skill
  有效租约；达到上限时跳过该任务并继续寻找其他 Skill。
- 执行租约：Worker 领取时写入 `worker_id`、`attempt_count`、心跳和租约到期时间。
  执行期间独立心跳续租；只读标准任务可在租约过期后有限重排，高风险写入和
  Workflow Action 失败后必须人工检查，防止重复写入。
- 本地 SQLite 使用 WAL、30 秒 busy timeout 和 `BEGIN IMMEDIATE` 完成原子领取；
  PostgreSQL 使用 `scheduler_locks` 行锁。多机正式部署推荐 PostgreSQL。
- 对话上下文：数据库保存完整消息；每次请求向模型发送稳定系统规则、结构化工作流
  状态和最近 20 条消息。模型可直接自然回复，只有明确推进任务时才调用当前阶段工具。
- 自然语言中出现“开始、停止、确认写入”等词不会自动执行；本地确定性规则只接受
  明确指令，写入确认还需后端二次校验最新用户原话。
- React：Skill 目录、参数解析、任务提交、实时进度、结果下载和管理员页面。
- Skill Registry：扫描 `skills/*/tool.yaml`，也可配置外部 Git 工作树。
- Model Connections：API Key 自动探测、加密保存、模型发现和任务级模型选择。

## 模型接入流程

```mermaid
flowchart LR
    A["员工输入 API Key"] --> B["后端探测允许的供应商端点"]
    B --> C["验证密钥并读取模型列表"]
    C --> D["筛选支持 Tool Calling 的文本模型"]
    D --> E["加密保存 API Key"]
    E --> F["前端仅显示脱敏提示和模型名称"]
    F --> G["任务选择连接与模型"]
    G --> H["模型提取受 Schema 约束的参数"]
    H --> I["Skill 确定性执行财务任务"]
```

凭据密文保存在 SQLite，Fernet 主密钥位于 `data/credential.key`，两者都不进入
Git。生产环境应把主密钥迁移到公司密钥管理系统，并限制数据库和数据目录权限。

## 下一阶段

- PostgreSQL + Redis/Celery，支持多实例和可靠重试。
- Docker/Windows Sandbox 隔离 Python 与 RPA Worker。
- 接入公司 SSO/LDAP，替换当前演示身份头。
- Git Webhook 拉取批准版本，并增加签名、病毒扫描与依赖白名单。
- 增加审批流、审计导出、保留周期和数据脱敏策略。
