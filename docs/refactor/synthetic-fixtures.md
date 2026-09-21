# 合成样本登记

禁止使用 sources 下 conftest 默认指向的真实财务金标目录作为 CI 输入。所有新运行入口须显式选择已核实的合成构造器，临时生成、运行后销毁。

| 场景 | 已有构造入口 | 构造与预期业务含义 | 本轮验证 |
| --- | --- | --- | --- |
| 普通表格任务 | backend/tests/fixtures/generate_published_skill_inputs.py:reconciliation_inputs | 银行 100/200/999 与总账 100/200.5/700 的合成记录，用于匹配、金额差及未匹配分类；不使用银行原件 | ordinary-e2e 已通过实际上传、确认、Worker、产物登记与下载链路 |
| 多年账簿 | 同文件 receivables_inputs | 创建 2025/2026 sheet，各有非零与零金额项目，另有批量来源 sheet | 应收合并样本仅供普通表格任务；专用 AR 多年样本现复用 test_plan_apply.py:_ledger，分别生成 2025/2026 同行号但不同 SO/SOD 的最小盈亏表，来源 Skill 校验及 apply_all 两项通过 |
| 跨月流转表 | skills/ar-hexiao-daily/vendor/scripts/test_flow_monthly.py:MonthlyFlowTest | 9000 到账，7 月核销 1000，8 月承接 8000，再核销 3000 和 5000；预收保留完整文字算式，重复执行不改变文件 | 该模块 43 项通过 |
| 流转错误保持原表 | MonthlySafetyTest | 错误算式、超额扣款、倒序日期、无法证明父回款等合成边界 | 包含于上述 43 项 |
| 仅预填订单 | test_flow_order_only.py:OrderOnlyTest | 仅补订单，余额与更新应收状态保持；后续实收再扣减预收 | 有 1 项现有完成行行为差异，未通过 |
| 单日及多日取数材料 | scripts/refactor/synthetic_inputs.py | 两天各四表、每日期 100 核销；不请求智云 | 真实 xlsx 解析通过；平台 FetchedBundle/空日专项 21 项通过（见下文边界） |
| 写后失败与未发布材料 | test_refactor_postwrite_boundary.py | 旧版暂存写入后注入复核失败 | 专项通过；新版发布事务未覆盖 |
| Native/Pi 文件生成 | test_refactor_native_artifacts.py / test_refactor_pi_files.py | 合成产物、真实服务与 UDS | Pi 2 项通过；Native 被缺表阻断 |

合成 fixture 及基线已建立；Native 失败与各场景未覆盖边界在下文明确保留，不能据此宣称业务验收通过。

## 已验证的来源 Skill 样本

ar-source-synthetic 仅指定 test_yucun_so_and_flow_flag.py 与 test_plan_apply.py 中两个年度测试，7 项通过。AR_HEXIAO_TEST_DATA 强制指向本轮临时根，未读取 conftest 默认真实金标路径。

- 四表使用合成 AR/SO/SOD：100 核销额由 60+40 的 SOD 构成，150 的其他 SOD 不动。
- 两个年度的工作簿都使用明细第 2 行，校验以年度隔离，apply_all 处理两份工作副本并生成组合报告。
- 来源目录不等于线上固定快照或 vendor 副本，因此这些测试不能替代线上运行链全流程验收。
- 多日期平台取数包 DB 与完整任务链仍未覆盖；写后失败、Native/Pi fixture 的当前结果见下文。

## 可复用材料生成器

scripts/refactor/synthetic_inputs.py:create 在 verify_isolation 通过后创建全新目录。构造 2025/2026 各一份盈亏表、200 元到账流转表、2026-07-31 和 2026-08-01 各一套四表（各核销 100 元），共 11 份真实 xlsx。manifest 保存合成标记、年度映射、日期、期望余额和每份文件 SHA-256。期望金额是测试输入定义，不是工作流成功证据。

test_synthetic_inputs 使用当前 vendor classify_hexiao.load_exports 分别回读两天导出，验证本次核销合计各为 100；年度盈亏表保留回款字段空白。测试确认已存在目录无法被覆盖。生成与销毁均位于隔离临时根，未保留远程临时文件。19 项工具/样本检查通过。

生成器负责真实 xlsx 内容；FetchedBundle DB、写后失败与 Native/Pi 分别由下述专项覆盖或记录失败。

## Pi 分块传输与会话隔离基线

backend/tests/test_refactor_pi_files.py 两项测试通过：真实 pi_runtime_service → HTTP Unix socket → RuntimeManager.dispatch → pi_files，验证超过 1 MiB 的分块上传、SHA-256、合成产出经真实下载路由流式回读、Content-Length、跨块版本绑定、异用户在传输前拒绝、同用户另一会话不可读取，以及文件变化/目录穿越/符号链接拒绝。

边界：模型产出由合成文件写入替代，API 登录用户与审计 DB 使用 fixture，不证明实际认证登录、审计持久化、Docker 生命周期或完整 Pi 模型任务。没有外网、Docker socket 和生产挂载。测试模拟宿主 root 文件管理器；本地后端测试镜像默认 UID 10001，需使用 --user 0:0 并提供已安装测试依赖的 PYTHONUSERBASE。CI 干净测试镜像默认 root，依赖为系统安装。普通用户执行明确报测试前提不符，不放松文件管理器权限校验。

复验日志：本地 .scratch/refactor-20260918/pi-files-baseline-root.txt，退出 0；保留 Starlette/httpx 弃用警告。suite pi-files 已加入 CI 配置，GitHub 上尚未运行这个未提交版本。

写后失败 fixture 也已建立：test_refactor_postwrite_boundary.py 在旧版写入暂存后注入复核失败，验证原材料字节不变、不登记新产物、暂存清理；已通过专项。它不覆盖新版 14 阶段数据库发布事务。Native 产出 fixture 已存在，但新库缺 assistant_turns 的迁移问题使其未能到达产物断言，继续保留失败。

## 普通表格任务端到端基线

复用既有 test_platform_e2e.py::test_upload_run_worker_and_download，不另造简化执行器。合成银行金额 100/200/999，总账金额 100/200.5/700，在金额容差 1、日期容差 2 下匹配 2 笔，两侧各 1 笔未匹配。测试经认证 fixture 调用上传、模型连接（网络响应模拟）、Run 创建与确认、真实 run_once Python Worker，再查询产物归属并下载 Excel，核对三个 sheet 和记录行数。

只读源码、无网络、隔离 DB/tmpfs 条件下 1 项通过，命令退出 0；证据为本地 .scratch/refactor-20260918/ordinary-e2e-baseline.txt。未使用真实 API Key 或银行附件。它证明普通 Python 表格链路，不证明真实模型协议、PostgreSQL 迁移或业务核销批次。已加入 ordinary-e2e 独立 CI suite。

## 平台取数包与空日专项

check.py --suite fetch-bundle-synthetic 复用现有测试：单日 materialize_bundle 发布和 DB 记录；两个非连续日期仅暂存目标日期、重复暂存及内容变化检查；确认空日跳过分类/写入、取消拦截、空日原材料向后传递、末日范围报告和不可信空日标记拒绝。合计 21 项通过、退出 0，本地证据 fetch-bundle-synthetic-baseline.txt。

取数包服务 fixture 的 xlsx 扩展名成员实际为合成字节，专门验证存储成员和哈希，不证明 Excel 内容解析；真实 xlsx 解析由 synthetic_inputs 与 ar-source-synthetic 独立验证。空日单元测试使用合成服务对象，不等于完整 31 日生产批次验收。所有组件证据分别记录，不把它们合称全流程生产通过。
