---
name: ar-hexiao-daily
description: 按明确核销日期执行应收核销：读取智云导出和当前年度盈亏表，生成核销日清，校验后写工作副本并回读；也支持只分析挂账冲突和只生成清单。
---

# 应收核销日清

独立包版本 2026.09.16.1，取自当前线上正式版。AI 负责确认任务范围、准备材料、依次调用脚本和解释结果；金额、行定位、写入和回读由脚本处理。先读 [当前规则与边界](references/current-behavior.md)，环境准备见 [README](README.md)。

## 1. 固定任务与输入

固定具体核销日期、是否仅分析、年度文件与流转表。用户给出连续日期时按日期升序分别处理；每年只选一份盈亏表，流转表只选一份。日期或同年材料有多个候选且无法从任务确定时询问用户。

每次新任务建立独立工作区 WS，创建 `01_智云导出`、`02_我的表副本`、`03_台账`、`04_产出`。把用户选定的盈亏表和流转表复制到 `02_我的表副本`，保存原件路径与SHA-256；只把这些副本路径交给写入脚本。源文件和便携版均不作为写入目标。

新批次不从其他目录自动搜集历史台账。明确继续同一批次时保留该批次台账及上一成功日的工作副本；当前程序仍会使用其中部分历史记录，详见规则。创建包、检查问题、演示或安装不构成执行真实核销的授权。

完成条件：核销日期明确、材料年度唯一、副本与原件隔离、完整记录本次输入。

## 2. 取数与写前检查

以下命令从包根目录执行。`<WS>`、`<DAY>`、`<YEAR>` 和 `<LEDGER>` 必须替换为本次绝对路径或具体值；多年度时重复 `--ledger-year YEAR=PATH`，每个后续步骤使用相同映射。先用各脚本 `--help` 核实参数。

```text
python scripts/check_package.py
python scripts/fetch_zhiyun.py --workspace <WS> --date <DAY> --force
python scripts/verify_sources.py snapshot --workspace <WS>
python scripts/inspect_inputs.py --workspace <WS>
python scripts/classify_hexiao.py --workspace <WS> --hexiao-date <DAY> --ledger-year <YEAR>=<LEDGER> --out <WS>/04_产出/判定结果_<DAY>.json
python scripts/build_flow_plan.py --workspace <WS> --result <WS>/04_产出/判定结果_<DAY>.json --out <WS>/04_产出/流转写入计划_<DAY>.json
python scripts/validate_plan.py --workspace <WS> --plan <WS>/04_产出/判定结果_<DAY>.json --ledger-year <YEAR>=<LEDGER> --out <WS>/04_产出/写入计划_<DAY>.json
python scripts/build_worklist.py --workspace <WS> --result <WS>/04_产出/判定结果_<DAY>.json --checked <WS>/04_产出/写入计划_<DAY>.json --flow-plan <WS>/04_产出/流转写入计划_<DAY>.json --out <WS>/04_产出/核销日清_<DAY>.xlsx
```

已有本次日期的完整、可验证智云导出时可以省略联网取数。认证使用运行环境中的 `ZHIYUN_USER`、`ZHIYUN_PASS`、`ZHIYUN_BASE` 或 `MD_PSS_ID`；凭据只由用户的环境或凭据库提供，不写入包、命令参数、日志或结果说明。

补跑历史日期时按明确范围调用 `audit_shifted_details.py` 检查父记录迁移，不擅自扩大财务日期。空日必须先核对导出完整性和目标日期，确认无业务后记为无核销；取数失败、缺文件和日期不符不能当作空日。

完成条件：来源日期和覆盖校验通过，判定、写前校验、流转计划及日清全部产生并核对笔数。用户只要求分析或清单时到此结束。

## 3. 写入副本与验收

用户已授权执行核销、写前校验通过并生成日清后，调用：

```text
python scripts/apply_all.py --workspace <WS> --checked <WS>/04_产出/写入计划_<DAY>.json --flow-plan <WS>/04_产出/流转写入计划_<DAY>.json --ledger-year <YEAR>=<LEDGER> --in-place --flow-in-place
```

执行顺序为盈亏副本写入及回读，再处理流转表并回读。保留脚本产生的备份、执行记录和逐笔差异。保留挂账、冲突、异常原因，不将其修改为成功；关联回款组须完整通过。写入或回读失败时停止依赖该状态的后续日期，保留失败现场并报告，不自动重复财务写入。不得使用 `--force` 绕过冲突。

完成条件：检查退出码、实际写入/跳过/冲突数量、逐格回读和订单写入差异；核对用户原件SHA-256不变。脚本保存成功不等于核销验收通过。只对有执行及回读证据的记录报告已写入。

## 4. 多日期与交付

每个日期显式指定本日输入输出路径；后一天承接前一天已验证成功的工作副本，不从原件重新开始。原始导出与日期级JSON按日保存。全部日期状态核实后按实际完成范围调用 `build_task_reports.py --workspace <WS> --date-from <START> --date-to <END>` 生成整合日清；空日期只有核验通过后才通过 `--empty-date` 声明。

交付核销日清、写后盈亏及流转副本、变更及差异清单、未解决项和对应日期。报告分别说明完成、部分完成、失败和未执行；不把旧批次报告当作本次结果。
