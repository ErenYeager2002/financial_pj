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
        U2 --> U3["模型只对当前 Skill 提取参数"]
        U3 --> U4["员工检查参数与文件"]
    end

    P4 --> U1
    U4 --> V["后端校验权限、Schema、文件归属、容差和幂等键"]
    V --> S["保存 Skill 版本、哈希与运行快照"]
    S --> R{"是否需要确认"}
    R -->|"是"| C["员工确认具体动作"]
    R -->|"否"| Q["进入任务队列"]
    C --> Q

    Q --> W{"选择隔离 Worker"}
    W --> WP["Python Worker"]
    W --> WR["RPA Worker"]
    W --> WH["HTTP Worker"]
    WP --> E["确定性 Skill 执行"]
    WR --> E
    WH --> E
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
- 独立 Worker：轮询数据库队列，按 `python`、`rpa`、`http` 池领取任务。
- React：Skill 目录、参数解析、任务提交、实时进度、结果下载和管理员页面。
- Skill Registry：扫描 `skills/*/tool.yaml`，也可配置外部 Git 工作树。

## 下一阶段

- PostgreSQL + Redis/Celery，支持多实例和可靠重试。
- Docker/Windows Sandbox 隔离 Python 与 RPA Worker。
- 接入公司 SSO/LDAP，替换当前演示身份头。
- Git Webhook 拉取批准版本，并增加签名、病毒扫描与依赖白名单。
- 增加审批流、审计导出、保留周期和数据脱敏策略。
