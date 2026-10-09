# CW06 / F4.A：各次执行记录只读展示

2026-10-08：源码、专项验证、双轴审查、线上部署与只读浏览器验收完成。这里只完成 F4.A 元数据查询，不代表完整 F4 或整体施工完成；目标保持 active，继续下一阶段。

## 完成行为与边界

复用 execution GET 与原安全索引，保留每个 action/attempt 的原意图、阶段完成、原材料版本与绑定摘要。后一次成功不覆盖较早未知。旧索引缺失、损坏、counter/身份冲突或截断显示未知；不按巨大 counter 展开假历史。

登记索引最多128，稳定选择已有动作身份后详细投影最多2048，展示最多256；身份选择仍遍历已加载集合，SQL预加载和整个GET成本未被限制。摘要仅覆盖本次详细投影，不能作为解除凭据。history 的 process_evidence_checked 与 authorizes_resume 恒false；不改变原准入、恢复、封存或财务规则。

接口类型按原 exporter/openapi-typescript 生成并检查。冻结85bb镜像的导出基线，确认原快照漏了既有 Pi capabilities/deliveries/history 与 execution/abandon 共4路径及AbandonRequest；完整生成保留这些路由，F4.A本身没有新增路径。

## 已执行验证

真实 read_execution、合成 ORM/SQLite、原 safety 登记与材料占用 seam：13 passed，0 skip，1.70s。覆盖双attempt、counter回退/清0/orphan、坏context/state/index/UUID/时间、日期身份、巨大counter单缺口、128/129、2048/2049稳定重排、256/257优先原记录、脱敏、partial fingerprint、legacy兼容及无DML/commit/ORM脏变更。不是PostgreSQL竞争测试或真实核销。

双轴最终审查 Standards 硬违规0 / Spec 阻断0；相关静态diff、合同检查、TS类型检查和离线前后端构建通过。未扩大为全量测试。

## 线上生效与浏览器验收

- API、worker-standard、worker-task-discovery 镜像：dca460d790555fc211f145ceab9089afb0fbc64ccb5749d6662f1a700d0b7a23。
- 前端镜像：b8990adbbaedda8b6de1f4490dfbe2bece9e6583036cd8cdcd6b49396ab9e603；540个构建输入，仅UI与generated两个输入相对原线上manifest变化。source digest ec0cd36a65b1011ebc6e877b9097a5eec4f762dd8437032431c65c6e433fc383。
- history源码/三后端：30b886da9b9db8b9ebd39fe242029f1f28e199b845c91fdadbaf8fecf61b1439；service：3e088314e0bdf4e52b529b626bb66ca5cbc3c1a2e881aea7cb82c02a3afaae9d。
- UI：5251ddc3f280bd48221f3494f8b716684978ba2bd1407d28e451460a9002fa94；JSON：36e9390c444fe32d8234d76c4b7e177bbad776cc1f3dd5e7801ad6d484626ae7；TS：8ce0009820d1b9c5db74fa4dc8137068e6238d852123910a1a5d1edc496245c8；测试：788b00b276cea1fb91778326d150a311fde3c1242e82b15cc4eafe199b3aeeaa。
- 回滚：releases/managed-20261008-020130-bfa3975f（后端）、releases/managed-20261008-020415-c951418a（前端），位于部署根。按原发布锁、notice/drain/full及健康回读切换；normal恢复，API healthy、Worker running（无Docker Health字段）。独立回读活动计数全0，F1/F2/scheduler源码与运行哈希保留，3条历史封存marker未变，其中1条仍需调查。
- 浏览器登录实际批次 BAT-20260924-07ADB374 的2026-08-30，打开恢复处理/历史记录，API200与界面均显示已登记0、缺2、两条legacy_unknown。原停止证明不足警示保留，恢复/解锁/调查按钮0；console错误0。这里只验证查询与展示，不宣称已核清这两次业务效果或所有进程。

## 负面结果与处理

原打包helper使用上一轮前端旧哈希，准备检查失败后改以当前线上cfd960完整manifest核对。多次独立COPY后台追加层触发 mount options is too long；验证85bb恰为cddc9加F2 worker一层且运行Config相同后，以cddc9单次COPY worker与本次文件，候选与当前均456层、所有F1/F2及目标哈希一致，无宿主配置或镜像清理。首次前端发布锁忙，未切换；锁释放后重新完整预检并发布。早期red、fixture与helper失败日志保留在本地，不隐藏为全程首次成功。

没有真实核销、重跑、调查、解除、业务工作簿写入或权限变化。没有本阶段commit/push；上轮GitHub同步6476660已完成，不代表本阶段新增代码已推送。

## 续接节点

源目录 /home/lee/financial-platform-isolated/refactor-worktrees/full-platform-20260918，部署根 /home/lee/financial-platform-isolated。新AGENTS在源码、部署、本地入口统一SHA5ea6a3e879ec6b34a37f85519a656617b1562f5d226ac54be47690b3dc603206；按用户最新补充在上下文接近容量时保存节点。

下一步F4.B：prepared排他事实创建后、Popen前登记不可变原refs，复用原index/action/audit，先确定最小内部seam及故障窗口测试。只读准备在本地 .scratch/pi-construction-20260923/f4b-readonly-preparation-20261008.md 与原完整F4设计中；尚未实施F4.B，不扫描目录补造原登记锚点。

完整F4还缺多attempt进程/业务调查及管理员条件处置；F5发布实际文件+DB故障矩阵、F3安全有限重试、A25维护公平性、F6生命周期fixture、G4全Pi浏览器矩阵、CW09权限元数据、CW10条件DeerFlow适配及CW11最终检查仍未完成。整体继续，不因F4.A交付自动暂停或宣布完成。
