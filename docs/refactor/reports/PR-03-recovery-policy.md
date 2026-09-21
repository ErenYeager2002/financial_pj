# PR-03 受限恢复政策

候选镜像：`sha256:826d3ab09bccbe654f8f0f8cdc7c37ee10a79abd1053ace6029d13f61b6650c3`。恢复镜像：`sha256:917890ff4cb7d01d73d47704954d8e7cb76c91867d53652223fd225c51af5335`。

恢复镜像与候选共享已经验证的 PR-02/PR-03 安全核心，但通过镜像内环境 `FINANCIAL_SUBMISSION_REPLAY_ONLY=true` 启用独立的受限行为；它不是旧业务代码回退，也不是完整正常服务恢复。它保留数据库 f3 和所有提交绑定，禁止无 receipt 或未 bound 的普通任务、重试及草稿提交进入准备、接管 token 或创建任务；已 bound 请求仍执行指纹和当前权限检查后返回原任务。Worker 保留 PR-02 事务保护。Native/工作流使用当前候选既有实现，不切换到旧 writer。

`GET /api/submissions/{request_id}` 与网页 BFF 提供只读状态，按当前 owner、department、operation 及工具权限过滤，bound 时再次核对关联 run。只返回登记ID、操作、状态、run ID和响应版本，不暴露token、输入、文件、模型连接或指纹。恢复503对已有记录保留request_id；未知/新请求不虚构登记。

隔离 PostgreSQL：编排7项、实际普通HTTP4项、草稿5项通过；覆盖恢复拒绝不创建receipt、不换token、成功重放、异参、撤权和跨用户/部门查询。前端源码及对应测试的类型检查通过。实际候选及恢复镜像的f2→f3、重复迁移、只读启动、事务及Worker故障探针通过；恢复镜像额外核对默认模式、拒绝新登记、原bound重放且没有新建run。

恢复脚本 `scripts/refactor/build_pr03_recovery.py` 仅发送Dockerfile作为构建上下文，精确固定已验证本地候选镜像，不下载依赖。当前生产Compose无同名环境覆盖。发布若进入此恢复镜像，应明确报告普通新提交暂不可用，不将维护页面解除等同于全功能恢复。无法通过兼容检查时保留维护状态并继续诊断，禁止回退未经保护的旧writer。
