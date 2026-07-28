# 财务 Skill 接入目录

平台共登记 18 个 Skill。`published` 可由普通财务用户直接选择运行；
`draft` 已完成目录接入但仍缺少安全执行条件；`disabled` 保留说明和来源，
修复阻断项前不会出现在普通用户的工具目录中。

## 已发布

| Skill | 用途 | 执行方式 |
| --- | --- | --- |
| `reconcile-bank` | 银行流水与财务总账匹配 | Python |
| `receivables-merge` | 合并本期应收台账并回填上一版 | Python 桥接 |
| `split-by-sales` | 应收 all 按销售人员拆分 | Python 桥接 |
| `ar-hexiao-daily` | 应收核销日清，写前双重人工确认 | 对话式工作流 |
| `labor-invoice-check` | 劳务清单与发票台账核对 | Python 桥接 |
| `withholding-report-rename` | 申报表 PDF 规范命名副本 | Python 桥接 |
| `compliance-spot-check` | 生成本周合规抽查建议 | Python 桥接 |
| `dreame-ar-progress-diff` | 多版本应收进度变化对比 | Python 桥接 |
| `dept-expense-alloc` | 部门费用归集分摊 | Python 桥接 |
| `order-daily-summary` | 使用九点导出表生成下单统计 | Python 桥接（离线） |

## 已登记但暂未发布

| Skill | 状态 | 阻断原因 |
| --- | --- | --- |
| `jdy-cashflow-export` | draft | 需要独立凭据保管与受控浏览器会话 |
| `jdy-cashflow-reconcile` | disabled | 当前缺少会计期间维度，同号凭证跨月会被错误合并 |
| `task-clarifier` | disabled | Agent 行为指南，不是独立 CLI |
| `env-doctor` | disabled | 需要受控系统诊断适配器 |
| `xlsx` | disabled | 文档型 Agent 基础能力 |
| `pdf` | disabled | 文档型 Agent 基础能力 |
| `docx` | disabled | 文档型 Agent 基础能力 |
| `pptx` | disabled | 文档型 Agent 基础能力 |

## 同步与运行边界

- 源仓库：`EvanLee2004/finance-skills`。
- 平台保存审查后的本地副本，并在每次运行前固化整个 Skill 快照。
- 输入文件复制到本次任务工作区；文件名保留原名称信息，便于日期识别。
- 旧 CLI 的产物必须写入本次任务输出目录，平台再登记下载链接。
- 多文件输入可声明 `min_files`；例如进度对比至少需要两份工作簿。
- 对话式工作流只能调用当前阶段白名单动作；`ar-hexiao-daily` 在确认日期后
  才能生成日清，在员工检查并二次确认后才能写表。
- RPA Worker 默认不开启，配置完凭据保管与浏览器隔离后才加入 `rpa` 池。
