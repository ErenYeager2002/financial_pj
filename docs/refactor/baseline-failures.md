# 基线失败记录

## B001：后端测试收集失败

2026-09-18，提交 2cd58e9，独立镜像 financial-refactor-test:baseline-20260918，Python 3.11、pytest 8.4.2。只读挂载源码、network none、临时数据位于容器 tmpfs；未挂载生产数据。

backend/tests/test_feature_controls.py:7 从 app.feature_control_service 导入 TASK_DISCOVERY 失败。pytest 在收集阶段退出 2，尚不能推断其他用例结果。首次结果保存在本地 .scratch/refactor-20260918/backend-baseline-current.txt。

继续采集使用显式 --continue-on-collection-errors，原收集错误仍计为失败，不作为绿灯。PR-00 不为使基线变绿而恢复已移除的功能开关。后续应依据功能开关移除要求审核该历史测试。

## 尚未验证

真实 PostgreSQL 集成、前端全套构建、关键合成 E2E 和生产切换均未完成。

## B002：继续收集后的真实基线

同一隔离镜像、同一提交，显式 --continue-on-collection-errors，142.63 秒完成；pytest 报告 145 failed、562 passed、1 skipped、11 errors，退出码 1。完整本地证据：.scratch/refactor-20260918/backend-baseline-remaining.txt。

初步分类（不是全部根因已核实）：

- 10 个 RetentionGuardTests setup 错误明确要求 Disposable PostgreSQL test required；需要专用 PostgreSQL 测试环境，不能降级成 SQLite 后宣称通过。
- 1 个收集错误仍是 B001。
- OpenAPI frozen domain contract 期望旧版本字符串，与当前版本不一致；应核对契约演进记录。
- 若干 SimpleNamespace 测试对象缺 id；须逐项核验 fixture 与当前服务契约，不能删除业务身份检查。
- 用户停用、材料归属和历史绑定校验的失败需区分测试准备问题与业务回归；当前未改动这些业务判断。

所有失败保持可见；尚未证明线上存在同等数量故障。

## PostgreSQL 专项复核

已修复测试启动层：数据库 URL 经过隔离校验，原未定义 GUARD_SQL 改为加载 deployment/file_retention_guard.sql 正式源码。scripts/refactor/postgres_baseline.py 创建 network=none、无端口映射、数据 tmpfs 的专用 PostgreSQL；测试容器仅共享其私有网络命名空间。

10 项 RetentionGuardTests 全部通过（0.434 秒），覆盖并发写引用与删除互斥、历史引用保留及拒绝已删除文件重新引用。测试结束校验容器 label 后删除，复查无残留容器。证据：本地 .scratch/refactor-20260918/postgres-baseline.txt。该结果只覆盖文件保留 SQL，不代表所有 PostgreSQL 门禁通过。

## 前端预装依赖基线（环境不完全匹配）

使用 ai-chat-builder-20260915 依赖，当前源码复制到容器 tmpfs，network none，原源码只读。source lock hash cf195412254aaca683fc849a45e3930d0038382140a019589042d0e23d040525 与 builder lock hash 8fb2f088afac8eb87553655fccf047c8668d6a66335ab703a3ece9ce2fc54f0a 不同。因此不能以本结果证明当前锁文件构建结果。

- run-access 2、agent-wire 2、hydration 4 项通过，前端 contracts:check 通过。
- navigation 7 通过、3 失败；platform-data 6 通过、1 失败。
- lint 26 warnings、12 errors，尚未逐项分类。
- typecheck/build 缺少 @xterm/xterm 与 @xterm/addon-fit；这是预装 builder 与当前锁文件不一致的已知限制，需用当前 frozen lock 安装后复核。不能删掉 Pi 终端入口来消除此错误。
- 最初 pnpm 启动受 Corepack 冷缓存联网请求阻断，改用 npm run 执行既有 scripts（没有 npm install，也没有更改锁文件）。

完整本地证据：.scratch/refactor-20260918/frontend-baseline-npm.txt。下一步是匹配锁文件的测试构建环境，而非把当前失败当作最终前端基线。

## 前端锁文件依赖镜像超时

构建 financial-refactor-web-test:lock-20260918 在 520 秒超时，包装进程终止 docker build 客户端。再次核实客户端 PID 不存在、目标 image inspect 不存在。尚无有效新镜像，不重用旧镜像宣称复验完成。原构建输出由子进程缓冲，未得到失败前日志，因此目前无法证明具体卡点或网络根因。下次构建必须采用流式日志并保留终止状态。生产容器未重启。

## 前端构建卡点复现与修正

实时日志复现 pnpm 的旧 node_modules 重装确认提示；已精确取消该测试构建（退出 130），无生产服务变更。启用 CI=true 后安装立即进入下一阶段，并明确报 ENOENT /app/agent-runtime。说明仅替换 web 锁文件不足以重建本地 file dependency。

Dockerfile.frontend-test 现显式复制并按冻结锁文件构建 agent-runtime，再安装 web，保留 pnpm 10.15.1，并限制下载重试/等待。完整流式日志位于本地 .scratch/refactor-20260918/frontend-image-build-runtime.txt。本轮正在构建，未宣称成功。旧基础镜像仍只用作 Node 环境加速，干净基础镜像验证由 CI/后续构建承担。

## 合成到账流转基线

无网络、只读挂载源码、tmpfs 合成工作簿条件下：test_flow_monthly.py 43 项通过。test_flow_order_only.py 88 项执行，其中 1 项失败（该模块继承并重复运行基础测试，不应汇总为 131 个独立场景）。

失败：OrderOnlyTest.test_existing_completed_status_is_not_overwritten。样本 G2=是；测试期望工作簿不变且返回错误，实际程序在不改变完成标志的情况下补写 E2 的 SO 信息。这是测试契约与当前行为的具体差异，尚未判定应修改哪一侧；未改财务逻辑。日志：本地 .scratch/refactor-20260918/ar-synthetic-baseline.txt。

## 匹配锁文件的测试镜像

financial-refactor-web-test:lock-20260918 构建已成功（BUILD_EXIT 0），Agent runtime 与 web 均使用各自 frozen lock；新增 xterm 依赖已安装。先前旧 builder 缺依赖导致的 typecheck/build 结果不能作为最终代码判断。当前正在用新镜像进行复验，证据文件 .scratch/refactor-20260918/frontend-baseline-locked.txt 完成后读取。

来源 Skill 合成专项 7 项通过（0.50 秒），只覆盖四表解析、SOD 金额匹配与年度写入测试，不代表工作流全量通过。日志：.scratch/refactor-20260918/ar-source-synthetic-baseline.txt。

## 前端冻结依赖复验完成

source 与 builder 的 pnpm-lock.yaml SHA-256 均为 cf195412254aaca683fc849a45e3930d0038382140a019589042d0e23d040525。typecheck、生产 build、contracts:check、run-access、agent-wire、hydration 通过。完整结果：本地 .scratch/refactor-20260918/frontend-baseline-locked.txt。旧环境 xterm 错误已排除。

仍失败：格式检查 135 文件、lint 12 errors/26 warnings、navigation 3 用例、platform-data 1 用例。构建保留 Google Sans Flex 字体 override 和 metadataBase 警告。不把这些既有问题掩盖为绿灯，也不在 PR-00 大范围自动格式化业务源码。

## Native 命令的新库迁移缺表

新增 test_refactor_native_artifacts.py 使用真实 native.execute_command、当前用户权限刷新、HTTP Unix socket 传输及真实 Run/File 登记；仅执行器用合成 Python 文件生成器替代，不能视为正式 sandbox 或模型验收。

实际运行在 require_turn_command 查询时失败：sqlite OperationalError，no such table: assistant_turns。同次日志证明 init_db 已执行全部 30 个 Alembic 迁移至 e0f1a2b3c4d5。因此新库迁移未满足当前 Native 调用链所需模型。未在测试中临时 create_all 绕过。该失败加入 CI 并保持可见；PR-01 需审查模型表与迁移链覆盖，PR-13 需继续验证命令收据与会话边界。

日志：本地 .scratch/refactor-20260918/native-artifacts-baseline.txt。尚未到达产物断言，不能宣称成果归档通过。未连接生产 DB。
