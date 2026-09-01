# 财务 Skill 源码与平台运行审计

审计日期：2026-08-31

Gitee：`https://gitee.com/Lee157/finance-skills.git`

固定提交：`0d8ff1737995a9b32143f6179ddf8738161e5cb1`

## 范围与结论

本次以 Gitee 固定提交、平台 `skills/*/tool.yaml`、桥接入口和实际脚本为依据，覆盖平台当前登记的 19 个 Skill。Gitee 和平台各有 19 个目录，但只重合 16 个：Gitee 独有 `kingdee-posting`、`qige-invoice-to-kingdee`、`update-finance-skills`；平台独有 `jdy-cashflow-export`、`jdy-cashflow-reconcile`、`reconcile-bank`。

平台已发布的普通业务 Skill 继续使用上传文件后本地确定性处理；只有 `ar-hexiao-daily` 直接读取智云。`order-daily-summary` 的源 Skill 支持登录智云，但平台发布版有意采用上传智云导出表的离线模式。`jdy-cashflow-export` 需要金蝶云浏览器 RPA，仍处于 draft，不能作为已完成可运行能力。

## 已发布业务 Skill

| Skill | 解决的问题 | 平台运行方式 | 输入 | 输出 | 是否去其他平台取数 | 改造结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `ar-hexiao-daily` | 智云回款核销、日清、挂账复扫及工作副本回填 | 多阶段 workflow | 年度盈亏核算表、到账流转表、核销日期 | 核销日清、差异报告、写入后的工作副本 | 是，直接只读访问智云；不写智云 | 标记“智云取数 / 复用业务材料 / 写入工作副本”，保留网络白名单、确认、变更复核和审批 |
| `compliance-spot-check` | 从应收台账生成本周内部合规抽查建议 | Python 离线文件处理 | 应收 all；可选抽查历史 CSV | 建议清单 Excel 和说明文本 | 否 | 标记“上传应收台账 / 本地生成建议 / 输出Excel” |
| `dept-expense-alloc` | 按人员、收入和科目规则归集分摊部门费用 | Python 离线文件处理 | 多份费用分摊材料 | 部门科目和利润分摊工作簿 | Skill 不直连；材料通常先从用友导出 | 标记“上传用友导出 / 本地归集分摊 / 输出工作簿”，网络保持关闭 |
| `dreame-ar-progress-diff` | 对齐并比较两个以上追觅应收进度版本 | Python 离线对比 | 按旧到新排序的多个 Excel | 进度变化对比报告 | 否 | 标记“上传多个版本 / 本地对比 / 输出报告” |
| `labor-invoice-check` | 支付前核对劳务清单、发票台账和豁免规则 | Python 离线核对 | 劳务清单、发票台账 | 主核对表、催票名单、可付名单 | 否 | 标记“上传两份台账 / 本地核对 / 输出支付清单” |
| `order-daily-summary` | 按工作日和组织架构生成九点下单统计 | Python 离线统计 | 智云导出的下单明细；统计日期和明细开关 | 部门汇总、可选明细、ZIP | 平台不直连；员工上传智云导出。源 Skill 的直连模式不在平台启用 | 标记“上传智云导出 / 离线统计 / 输出ZIP”，继续保持 `network_access=false` |
| `project-detail-to-ledger` | 把项目明细按 SO+SOD 去重补入盈亏核算表副本 | Python 离线文件处理 | 项目明细表、盈亏核算表 | 新工作簿副本和 JSON 补录报告 | 否 | 标记“上传两份工作簿 / 本地补录 / 输出新副本” |
| `receivables-merge` | 合并年度应收、计算账龄并回填上一版标注 | Python 离线文件处理 | 本期源台账；可选上一版应收 all；账龄基准月 | 新应收 all 工作簿 | 否 | 标记“上传应收台账 / 本地合并 / 输出新副本” |
| `reconcile-bank` | 按日期和金额容差匹配银行流水与总账 | Python 离线核对 | 银行流水、财务总账、两项容差 | 匹配明细和双方未匹配清单 | 否；不连接银行或 ERP | 标记“上传两份账表 / 本地对账 / 输出差异清单”；该 Skill 为平台独有 |
| `split-by-sales` | 把应收 all 按销售人员拆成独立工作簿 | Python 离线批处理 | 应收 all、结果日期 | 销售人员工作簿 ZIP 和对账统计 | 否 | 标记“上传应收台账 / 本地拆分 / 输出ZIP” |
| `withholding-report-rename` | 从申报表 PDF 识别名称和金额并生成规范命名副本 | Python 离线 PDF 处理 | 多份申报表 PDF | 规范命名 PDF 副本 ZIP | Skill 不直连；PDF 先从电子税务局导出 | 仅显示“只读或生成副本”，原件不变 |

## 已登记但未发布或非普通业务任务

| Skill | 状态与用途 | 运行方式 | 输入与输出 | 外部取数 | 改造结论 |
| --- | --- | --- | --- | --- | --- |
| `jdy-cashflow-export` | draft；逐项导出金蝶现金流量调整明细 | Selenium/Edge 浏览器 RPA | 受控凭据和浏览器会话；输出下载明细 | 是，登录金蝶云并执行查询和导出 | 标记“金蝶云RPA / 需要受控凭据 / 导出明细”；Gitee 当前无同名目录，保持 draft，接入凭据保管和隔离浏览器前不发布 |
| `jdy-cashflow-reconcile` | disabled；核对现金流量明细表与整合表 | Node.js 离线核对 | 两份明细表；输出标色工作簿和异常汇总 | 否 | 标记“上传两份明细 / 本地核对 / 输出差异表”；Gitee 当前无同名目录，补齐受控 Node 运行时和专属双文件体验后再评审 |
| `env-doctor` | disabled；平台健康与依赖诊断入口 | Agent 指南/诊断页面 | 当前环境状态；输出脱敏诊断摘要 | 平台诊断不访问业务系统 | 标记“环境诊断 / 不处理业务数据”，不作为普通财务任务发布 |
| `task-clarifier` | disabled；补齐任务目标、输入和限制 | Agent 对话 | 自然语言和可选文件；输出结构化任务草稿 | 否 | 标记“对话澄清 / 生成任务草稿”，继续走 AI 助手入口 |
| `xlsx` | disabled；Excel 通用创建、编辑和校验 | 文档 Agent | 本地表格；输出新表格或检查结果 | 否 | 标记“本地表格 / 创建与编辑”，不使用普通业务 Skill 表单 |
| `docx` | disabled；Word 创建、修订、批注和版面校验 | 文档 Agent | 本地 Word 文档；输出新文档或检查结果 | 否 | 标记“本地文档 / 创建与编辑” |
| `pdf` | disabled；PDF 读取、填表、拆分合并和渲染 | 文档 Agent | 本地 PDF；输出 PDF、图片或检查结果 | 否 | 标记“本地PDF / 读取与编辑” |
| `pptx` | disabled；演示文稿创建、编辑和视觉检查 | 文档 Agent | 本地演示文稿；输出新演示文稿或检查结果 | 否 | 标记“本地演示文稿 / 创建与编辑” |

## Gitee 独有目录

| Skill | 源码行为 | 平台处理结论 |
| --- | --- | --- |
| `kingdee-posting` | 识别销项、付款或收款材料，直接只读调用金蝶 OpenAPI 校验客户、供应商、职员和部门档案，生成凭证引入 Excel；不执行引入、审核或过账 | 作为新候选单独立项。接入前必须修复 Windows 下同一 PDF 被大小写 glob 重复计数的问题，并使用平台凭据保管、网络目标白名单、专属多场景输入体验和导入文件复核，不自动发布 |
| `qige-invoice-to-kingdee` | 本地把琪哥发票簿转换成金蝶凭证引入模板，不直连金蝶 | 功能已被 `kingdee-posting` 的销项场景覆盖；保留为来源兼容候选，不作为第二个同类员工入口自动接入 |
| `update-finance-skills` | 访问 Gitee/GitHub 并更新本地 Skill 包 | 属于管理员源码维护能力；继续排除在员工业务 Skill 之外，平台使用受控单 Skill 发布流程 |

## 固定提交测试基线

在隔离目录对 Gitee 固定提交执行全量测试，得到 7 个失败。逐文件复跑后确认：`ar-hexiao-daily` 的 1 个失败来自全量测试时同名模块污染，单文件 10 项通过；`order-daily-summary` 的 5 个失败来自测试文件把本地 `coverage.py` 与已加载的 Python `coverage` 包混淆，属于测试隔离缺陷；`kingdee-posting` 的 1 个失败可稳定复现，在 Windows 大小写不敏感文件系统中，`*.pdf` 与 `*.PDF` 会把同一发票计入两次，导致票额不足时未转为待确认。最后一项已作为该候选 Skill 接入平台前的阻断条件。

## 已实施改造

1. `SkillManifest` 增加统一 `operational_profile`，声明执行类型、外部来源访问方式和员工标签。
2. Registry 校验直接读取、浏览器 RPA 和仓库同步必须启用网络，RPA handler 与浏览器 RPA 画像必须双向一致；上传外部系统导出不因此开放网络。
3. 员工目录接口只返回 `operation_labels`，不返回外部来源结构、网络目标、凭据、仓库或 Commit；标签本身也拒绝地址、账号值、密钥、路径和源码版本。
4. 19 个平台 Skill 全部补齐内部运行画像；员工 Skill 目录卡片和详情页不显示运行画像等普通标签，只保留专属员工标签。
5. Gitee 同名 Skill 的来源元数据统一为 Gitee；Gitee 缺失的两个金蝶现金流量 Skill 不再声明虚假的 Gitee 路径。
6. `scripts/sync_finance_skills.py` 记录全部 19 个平台画像：同步 Gitee 可映射项，明确跳过并保留三个平台独有 Skill，后续受控更新不会覆盖本次信息。

## 后续发布边界

本次没有改变任何 Skill 的 published、draft 或 disabled 状态，没有登录业务系统，也没有执行真实取数、核销、导入、审核或过账。Gitee 独有目录必须分别经过来源绑定、输入契约、执行体验、凭据和网络评审，不能因为源码存在就直接进入员工目录。
