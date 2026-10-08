# CW09 实际能力来源与剩余边界

核验时间：2026-09-29T10:30:15.417933+00:00；API 镜像：`sha256:ebd548185c7a39352218c90fc7dae9e7293306ae8843f9e74df0278f64adc956`。本记录为只读盘点，不改变发布、安装、权限或外联。

## 两类执行来源

- 固定工具：沿用 Registry/tool.yaml、既有 Worker/workflow，权限 ID 为工具 ID。
- 仓库 Skill：沿用原生安装索引与固定提交包，权限 ID 为 `native--<id>`，用户按原方式安装；不新增作者必须提供的安装清单。
- 原生会话只挂载服务端记录的明确绑定；通用会话默认空挂载。包版本来自固定提交目录，管理器检查目录与符号链接。
- 新增的会话 capabilities 只是当前身份、现有授权与已支持控制命令的只读投影；实际执行仍重新鉴权，不授予新能力。

## 固定工具现状

| ID | 版本 | 状态 | 执行入口 | 声明副作用 |
|---|---|---|---|---|
| jdy-cashflow-export | 1.0.0 | disabled | rpa | external_action |
| labor-invoice-check | 1.0.0 | disabled | python | read_only |
| compliance-spot-check | 1.0.0 | disabled | python | read_only |
| task-clarifier | 1.0.0 | disabled | python | read_only |
| env-doctor | 1.0.0 | disabled | python | read_only |
| jdy-cashflow-reconcile | 1.0.0 | disabled | python | read_only |
| reconcile-bank | 1.0.0 | disabled | python | read_only |
| ar-hexiao-daily | 1.6.28-local.35.sales.4.balance.5 | published | workflow | write |
| ar-hexiao-daily-lab | 1.6.24-lab.6.local.35.sales.9.balance.35 | published | workflow | write |
| receivables-merge-and-split | 1.2.1 | disabled | python | read_only |
| dreame-ar-progress-diff | 1.0.0 | disabled | python | read_only |
| pdf-compress | 1.0.0 | disabled | python | read_only |
| withholding-report-rename | 1.0.1 | disabled | python | read_only |
| xlsx | 1.0.5 | disabled | python | read_only |
| pdf | 1.0.0 | disabled | python | read_only |
| pptx | 1.0.0 | disabled | python | read_only |
| docx | 1.0.0 | disabled | python | read_only |
| order-daily-summary | 1.0.0 | disabled | python | read_only |
| project-detail-to-ledger | 1.1.0 | disabled | python | read_only |
| consolidated-statements | 1.0.11 | disabled | python | read_only |
| dept-expense-alloc | 1.0.0 | disabled | python | read_only |

共21项，2项已发布、19项已停用，Registry 解析错误0。此处描述现状，未擅自启停既有工具。

## 原生 Skill 固定包

| ID | 固定提交 | 当前内容 SHA-256 |
|---|---|---|
| ar-hexiao-daily | `23a456aca7f497c72561b2391350e88f67d77f6a` | `823989ae1d3b6e5c4d47d4ddda4e615b7afe908c58f50187960c5342e4c136cc` |
| consolidated-statements | `aab80a85d197e108a0e3a41421c2dc8e0f8e0506` | `3d84d1d5d3a48aa2696ea79b62579a15249971eacc9f110ccc51031a0fadb5c1` |
| dept-expense-alloc | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `e3df04387b6f432f8756eec48418137ab04aae8ab05f4e9e6b9411706f91ddbf` |
| docx | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `e6495e4eea9c9a4698d98cc839b837162a85ccc1757082d34c4af0743671a06c` |
| dreame-ar-progress-diff | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `8221700d42d26fb0f69b4ba5f01368a5fbc716a6c4b6e1854b99951f0e31c4e5` |
| kingdee-gl-import | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `d2656a40e3f6d7f68841cc1ca7b588cc5d0749fe3bdf0117d3405d3627da1981` |
| kingdee-posting | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `143ada5bb30b14d0f803851253c8b855c520083ec83210b035d52b583caed127` |
| labor-invoice-check | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `926a44c45f2707448d80d197e27a515c7d7e2a9449685faaacd76c1fc452b70f` |
| pdf | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `c5191bb2d22a8bfd72e46839d9d83d0fa59ecfd05e947833c46ae27430aa09c3` |
| pl-dept-report | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `b13f86c771fb87b01f03e2761300e960324ed866a618255509cdc566fa49d20e` |
| pptx | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `c5419406fc9ce2d5defe0a3167896793fc74e54f2cf4958676b5d64b57bbfae7` |
| project-detail-to-ledger | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `6a884fc8fc03625bb99148fbcddee34a88a99cea37ab5901864ededa0662ce44` |
| receivables-merge | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `be399d488d8b5b5d129ff3be66456cdfadbfc15cbaee088db1a21572273761dd` |
| split-by-sales | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `e62cb81a269b12d7af69ccb141b926bee773219d7e14e5bfb1cd73d0d6e07b43` |
| withholding-report-rename | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `0675e6ef671931c045e14cc8f1708aa806b01be8efbefb06e1ec2a9f16ef9e60` |
| xlsx | `17f7f96b4fd3e1e63220263f778612948c01e7a8` | `8a464834664a1db92ccf2918bc8fd8ef36bdadb8805fc0be0dc3386f4aabc381` |

16个包均存在且未发现符号链接。内容哈希为本次只读观测，不代替安装审批，也不代表所有业务逐项实测。

## 已有控制边界与缺口

- Pi 网页公共控制仅开放当前已适配的命令；拒绝额外 owner/approved/路径/SQL 等字段。模型内部工具与公共 RPC 接口分别处理。
- 业务查询通过现有 query_platform 与服务端凭据映射，权限在查询时重核；本轮没有增加正式任务创建或财务写入工具。
- 固定工具有风险、外部系统、输入输出和版本哈希字段；原生安装索引没有结构化外部系统、恢复规则等字段。这些值保留未知，不从自然语言描述推导为允许。
- 当前模式与外联批准的完整逐项对照仍需补齐；本轮保留既有执行来源，不把旧 ADR 的瞬时离线沙箱说明冒充当前持久 Pi 的部署事实。
- 18项隔离回归验证文件隔离、文件变版、管理员停止、投递去重；真实财务写入未执行。
- 后续新增外部能力仍按具体对象审核；这不是新增安装标准，也不扩展现有授权。
