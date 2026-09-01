# 财务 Skill 源码审计与运行画像改造

Status: ready-for-human

日期：2026-08-31

## 目标

以 Gitee `https://gitee.com/Lee157/finance-skills.git` 的固定提交和平台当前 Registry 为证据，逐个说明平台现有 Skill 解决的问题、运行方式、输入、输出、是否需要从其他系统取数，并把这些信息变成可校验的运行画像和员工可见标签。

## 当前事实

- Gitee `main` 固定提交为 `0d8ff1737995a9b32143f6179ddf8738161e5cb1`，远端和平台各有 19 个 Skill，但只重合 16 个。
- Gitee 独有 `kingdee-posting`、`qige-invoice-to-kingdee`、`update-finance-skills`；平台独有 `jdy-cashflow-export`、`jdy-cashflow-reconcile`、`reconcile-bank`。
- 现有 Manifest 已声明文件、参数、输出、风险和网络权限，但没有统一声明真实运行方式及外部数据来源；员工页面也没有显示 Manifest 的业务标签。
- `order-daily-summary` 源码支持登录智云取数，平台发布版有意采用上传导出表的离线模式，必须保留该差异。

## 方案

1. 在 `SkillManifest` 增加统一运行画像：执行类型、外部数据来源、访问方式和员工标签。
2. 员工目录接口中的运行画像信息必须脱敏；外部地址、凭据和源码路径仍只属于管理员与运行配置。
3. 所有 19 个平台 Skill 都必须声明运行画像，Registry 缺失时拒绝加载。
4. 对直接取数、浏览器 RPA、上传其他系统导出、本地处理、Agent 指南和文档能力分别建模，不能用一个“联网”布尔值代替业务事实。
5. Skill 目录卡片和详情页不显示分类、风险、运行、取数、预计时长或版本状态标签，只保留管理员可见的专属员工标签。
6. `scripts/sync_finance_skills.py` 成为 Gitee 同步生成画像的持久来源；同步后的平台副本不得丢失画像。
7. 形成固定提交下的全量审计报告，记录 19 个平台 Skill 及远端独有候选的用途、运行、输入、输出、外部依赖和改造结论。

## 运行画像接口

- `execution_kind`：`offline_file`、`guided_workflow`、`browser_rpa`、`agent_guidance`、`document_agent`。
- `external_sources[]`：系统名称、`uploaded_export` / `direct_read` / `browser_rpa` / `repository_sync` 访问方式、是否为必需来源。
- `employee_labels[]`：1 至 4 个面向员工的短标签，不含地址、账号、密钥或源码信息。

## 安全规则

- 员工接口不得返回网络目标、凭据模式、仓库地址、Commit 或内部目录。
- `direct_read` 和 `browser_rpa` 必须与 `runtime.network_access=true` 一致；`uploaded_export` 不得据此打开网络。
- 运行画像不扩大 Skill 权限，不改变已禁用或草稿 Skill 的发布状态。
- 不执行真实财务任务，不登录智云、金蝶或其他业务系统。
- 不覆盖当前工作区中的无关改动。

## 验收

- 19 个平台 Skill 全部通过运行画像模型与一致性校验。
- AR 显示智云直接取数；九点下单显示上传智云导出和离线统计；金蝶导出显示浏览器 RPA 且仍保持 draft。
- 纯本地 Skill 不声明直接外部访问。
- 员工目录与详情页只显示专属员工标签，不显示运行画像标签，也不出现网络目标、凭据或源码字段。
- Gitee 同步暂存校验保留画像，源目录与平台发布副本的生成规则一致。
- 后端定向与全量测试、前端测试、类型检查和生产构建通过；已有无关失败单独说明。

## 非目标

- 不自动发布 Gitee 独有 Skill。
- 不把 `update-finance-skills` 变成员工业务 Skill。
- 不开放 `order-daily-summary` 的智云网络访问。
- 不在本任务中执行真实取数、核销、导入、审核或过账。
