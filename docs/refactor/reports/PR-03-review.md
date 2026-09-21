# PR-03 双轴审查与修复（2026-09-20）

比较基线 `2cd58e91348ff566250f03b882f22c46425bbe1f`，当前 HEAD `6fce5bf1195c0591d8f8cfb53b84c32c0356f36d`。审查包含未提交和未跟踪的 PR-03 文件，规格为 execution-guide.md §§5.2–5.5、6.5。两个独立只读审查分别负责规范与规格，无部署或真实业务操作。

## Standards

确定规范缺口一项：结构化提交冲突未声明在 OpenAPI。已增加 SubmissionErrorDetail/SubmissionConflictResponse，创建、重试、草稿确认三个入口声明 409；更新对应契约并重生成 TypeScript；前端透传使用生成类型。第二次静态审查确认修复，类型检查与错误透传测试通过。

判断项两项仍保留：前端对象排序函数重复；pinned_revision_json 多处以无类型字典解析，建议版本化严格 DTO。未将判断项冒充已发生的数据错误。

## Spec

确认两项主要缺陷并补充回归：

- 草稿首次确认失败保留 receipt 后，修改输入仍复用 draft:id，导致永久异参冲突。新增 content_revision（未发布 f3 迁移内），真实内容变化递增，key 为 draft:id:revision。无变化 PATCH 不递增；最终锁内比较包含 revision 的原请求，旧准备不能消费新版草稿。
- prepared 后发布新工具版本，草稿恢复仍解析最新 registry。现在先按当前草稿 intent 查询 receipt，使用固定版本检查；最终消费使用实际 run 的固定清单。仍检查当前用户、部门、权限、草稿与文件。

复核发现两个相关边界并修复：浏览器 PATCH 因 publication 返回409时，同输入 ready 草稿可以继续受后端校验的 confirm；不同输入、expired 和无有效 run 的 consumed 不允许。草稿修订比较使用稳定 JSON，避免 Python 将 1 与1.0等同而指纹不同。PostgreSQL 草稿专项5项通过，覆盖 prepared后发布、失败后改输入、数字类型变化、不变PATCH及撤权/文件/跨用户拒绝；浏览器草稿辅助流程4项通过。

## 镜像与当前状态

候选后端镜像 `sha256:bc561e0f3c6ba928f95b22064ae6b7afcae62d1c795f143b8afb95b9958db45b`。194个后端源码hash一致，UID10001，唯一head=f3a4b5c6d7e8，API导入通过。镜像内PG f2→f3升级、重复迁移、只读角色启动检查、事务回滚、Worker领取、独立进度、失败时丢弃未发布结果通过。证据见PR-03-image*.json/jsonl。

PostgreSQL事务38项、草稿锁2项、迁移8项通过。当前仅候选构建与隔离验证，未部署；正式前端、兼容回退、Native回填及上线回读仍需完成。普通既有7条历史记录未迁移绑定；旧key命中只拒绝新建，不自动选择或合并。PR-04至PR-21尚未实施。

## 前端构建复核

隔离 Next.js 生产构建第二次退出0，编译、类型检查、65页生成与standalone打包通过，见 PR-03-frontend-build-second.json。第一次768MiB临时空间不足导致打包ENOSPC，失败证据保留在PR-03-frontend-build.json；确认主机可用内存后，仅将独立构建容器tmpfs上限调整为2048MiB并重跑，未更改线上容器或主机配置。构建容器已自动删除，未产生正式前端发布镜像。Google Sans Flex字体覆盖与metadataBase既有告警保留，未视为构建错误或已修复。

最后只读发布检查仍normal，五类活动计数为0；静态diff检查通过。兼容回退、正式前端发布镜像、Native分批回填、浏览器验收和实际切换仍待完成；没有将候选构建报告当作线上生效。


## 2026-09-20 发布后补充复审

Spec确认准备失败后重解析缺少持久attempt事实。已在占位短事务追加started审计，独立UUID关联receipt；准备完成与prepared登记同事务，准备异常保留失败事实。commit异常独立回读prepared审计，已成功不追加失败，未确认记unknown。只保存attempt/operation，不保存key/token/模型原始响应或异常文本；进程崩溃保留未匹配started供核查。PG编排10项通过，含提交前与提交后应答丢失；外层业务回滚不删除这些独立事实。Spec最终只读复核无新增确定缺陷。

Standards发现frontend发布失败未自动恢复，已固定原运行镜像并增加恢复门禁。只检查其他受保护服务，允许Next已经不存在；仅恢复Next，健康与镜像通过才恢复normal。Compose操作超时保持待核验，不盲目重发。39项发布专项通过；Standards最终只读复核无新增确定缺陷。尚未人为制造生产故障验证恢复。

后端补丁镜像ccf975fae656实际发布与195文件哈希回读通过；前端882434f388fd已实际发布。Native295回填完成，旧字段保持不变。当前状态以上述最新报告为准，前文候选镜像和未发布状态均为历史记录。真实浏览器刷新重提未验收，本机Chrome连接器缺失app-server，不能用匿名HTTP探针代替。
