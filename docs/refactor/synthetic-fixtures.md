# 合成样本登记

禁止使用 sources 下 conftest 默认指向的真实财务金标目录作为 CI 输入。所有新运行入口须显式选择已核实的合成构造器，临时生成、运行后销毁。

| 场景 | 已有构造入口 | 构造与预期业务含义 | 本轮验证 |
| --- | --- | --- | --- |
| 普通表格任务 | backend/tests/fixtures/generate_published_skill_inputs.py:reconciliation_inputs | 银行 100/200/999 与总账 100/200.5/700 的合成记录，用于匹配、金额差及未匹配分类；不使用银行原件 | 构造源码已读，端到端尚未运行 |
| 多年账簿 | 同文件 receivables_inputs | 创建 2025/2026 sheet，各有非零与零金额项目，另有批量来源 sheet | 应收合并样本仅供普通表格任务；专用 AR 多年样本现复用 test_plan_apply.py:_ledger，分别生成 2025/2026 同行号但不同 SO/SOD 的最小盈亏表，来源 Skill 校验及 apply_all 两项通过 |
| 跨月流转表 | skills/ar-hexiao-daily/vendor/scripts/test_flow_monthly.py:MonthlyFlowTest | 9000 到账，7 月核销 1000，8 月承接 8000，再核销 3000 和 5000；预收保留完整文字算式，重复执行不改变文件 | 该模块 43 项通过 |
| 流转错误保持原表 | MonthlySafetyTest | 错误算式、超额扣款、倒序日期、无法证明父回款等合成边界 | 包含于上述 43 项 |
| 仅预填订单 | test_flow_order_only.py:OrderOnlyTest | 仅补订单，余额与更新应收状态保持；后续实收再扣减预收 | 有 1 项现有完成行行为差异，未通过 |
| 单日及多日取数包 | 待建立 | 应固定来源日期、完整性及空日证据，不请求智云 | 缺项 |
| 写后失败与未发布材料 | 待建立独立复用 fixture | 注入写后复核错误，必须保留原发布版本并禁止自动重写 | 缺项 |
| Native/Pi 文件生成 | 待建立隔离 fixture | 不调用真实模型，验证独立命令、成果登记与下载回读 | 缺项 |

已有测试内的 tmpdir 构造器可优先复用；缺项没有通过状态，尚未满足 PR-00 全部合成 E2E 要求。

## 已验证的来源 Skill 样本

ar-source-synthetic 仅指定 test_yucun_so_and_flow_flag.py 与 test_plan_apply.py 中两个年度测试，7 项通过。AR_HEXIAO_TEST_DATA 强制指向本轮临时根，未读取 conftest 默认真实金标路径。

- 四表使用合成 AR/SO/SOD：100 核销额由 60+40 的 SOD 构成，150 的其他 SOD 不动。
- 两个年度的工作簿都使用明细第 2 行，校验以年度隔离，apply_all 处理两份工作副本并生成组合报告。
- 来源目录不等于线上固定快照或 vendor 副本，因此这些测试不能替代线上运行链全流程验收。
- 多日期完整取数包、写后复核失败与 Native/Pi 文件生成的独立复用 fixture 仍待补齐。

## 可复用材料生成器

scripts/refactor/synthetic_inputs.py:create 在 verify_isolation 通过后创建全新目录。构造 2025/2026 各一份盈亏表、200 元到账流转表、2026-07-31 和 2026-08-01 各一套四表（各核销 100 元），共 11 份真实 xlsx。manifest 保存合成标记、年度映射、日期、期望余额和每份文件 SHA-256。期望金额是测试输入定义，不是工作流成功证据。

test_synthetic_inputs 使用当前 vendor classify_hexiao.load_exports 分别回读两天导出，验证本次核销合计各为 100；年度盈亏表保留回款字段空白。测试确认已存在目录无法被覆盖。生成与销毁均位于隔离临时根，未保留远程临时文件。19 项工具/样本检查通过。

该生成器已补充多日期四表材料；暂不生成平台 FetchedBundle 的 DB 记录。写后失败与 Native/Pi 运行链仍需专门验收。
