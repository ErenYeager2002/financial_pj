# Skill 接入协议

每个可执行 Skill 至少包含：

```text
skill-id/
├── SKILL.md
├── tool.yaml
└── scripts/
    └── entry.py
```

`tool.yaml` 定义身份、文件角色、输入/输出 JSON Schema、执行适配器、超时、并发和风险等级。平台只向普通员工展示 `status: published` 的 Skill。

多文件输入可在文件角色中声明 `min_files`，后端会在任务排队前校验数量：

```yaml
file_inputs:
  - role: versions
    name: 应收进度版本
    required: true
    multiple: true
    min_files: 2
    extensions: [xlsx, xlsm]
```

平台复制输入文件时会保留安全化的原文件名信息，便于旧脚本继续识别日期；
Skill 只能读取任务工作区副本，不能修改上传存储区中的原文件。

## Python 与 RPA 入口

平台调用：

```text
python entry.py --request <运行目录/request.json> --result <运行目录/result.json>
```

入口可以向标准输出逐行打印 JSON 事件：

```json
{"type":"progress","progress":45,"state":"running","message":"正在核对第 3 批数据"}
```

需要员工操作浏览器时：

```json
{"type":"notice","state":"waiting_user_action","message":"请在浏览器中完成登录"}
```

最终必须写入：

```json
{
  "status": "success",
  "summary": {"matched": 1189, "unmatched": 71},
  "output_files": [
    {"name": "对账结果.xlsx", "path": "运行目录内的绝对路径"}
  ],
  "warnings": []
}
```

输出文件只能位于本次运行目录。平台会重新计算 SHA-256、登记文件 ID，并把本地路径替换为受权限控制的下载地址。

## 对话式工作流

多阶段、人在环的 Skill 使用 `workflow` 适配器：

```yaml
handler:
  adapter: workflow
  worker_pool: workflow
risk:
  level: write
  requires_confirmation: true
```

工作流由后端状态机控制。模型只从当前阶段允许的 Tool Calling 白名单中选择动作，
不能提供脚本名、命令或路径。耗时动作写入 `WorkflowAction` 队列，由
`workflow` Worker 执行固化 Skill 快照中的固定脚本。

`ar-hexiao-daily` 的硬闸顺序为：

```text
确认核销日期 → 上传智云导出和两份财务工作簿 → 生成核销日清
→ 员工下载检查并明确确认 → 写入盈亏明细和流转安全子集 → 回读校验
```

确认日清前禁止调用写入脚本；模型服务不可用时仅允许本地受限意图解析，
不能绕过任何状态条件。

## Git 托管方式

Skill 可以维护在私有 GitHub 仓库。生产运行时不直接执行浮动的 `main` 分支，而是：

1. 管理员批准 commit 或 tag。
2. 平台拉取到受控工作树。
3. Registry 校验 `tool.yaml` 和入口。
4. 创建任务时复制不可变 Skill 快照。
5. 审计记录保留版本、commit SHA 和内容哈希。
