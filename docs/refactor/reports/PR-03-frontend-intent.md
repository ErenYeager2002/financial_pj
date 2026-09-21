# PR-03 前端提交意图

2026-09-20，SkillRunSetup 与 ConsolidationSetup 由固定 useRef key 改为 submissionKey。点击提交时按实际 JSON 请求计算稳定 SHA-256（对象键排序、数组保持顺序），sessionStorage 只保存摘要及随机 UUID，不保存原参数、文件名或业务内容。相同输入复用保存 key；参数/文件/顺序变化生成新 key；确认取得创建响应后按该 key 清理，旧请求成功不得删除较新的意图。失败保留 key；不可读取/写入存储时阻止发送，避免静默生成新标识；成功后的清理失败不把已成功任务误报失败。

存储按 run.create+skill 分组、限当前标签页会话，后端继续按 owner/department/operation 做真正隔离；浏览器 key 不是身份凭据。刷新后提交相同输入可复用保存意图，但此改动不持久化/还原整个表单内容，不能声称浏览器刷新自动恢复了所有参数及文件选择。

显式依赖已有锁文件和测试镜像中已存在的 @noble/hashes 1.8.0，使用其同步 SHA-256，兼容 HTTP 非 secure-context 页面。没有自行实现哈希算法或联网下载依赖。package 和 lock importer 有界更新，原完整包条目/完整性信息不变。

隔离 Node 测试总计 9 项通过（意图 4、结构化错误 2、草稿恢复 3），包含存储重建、网络重试、参数/数组变化、旧成功响应竞争、存储故障、无全局 WebCrypto、摘要与 Node 标准实现比对。只读挂载当前完整 src 到已有 web-test 依赖镜像，tsc --noEmit --incremental false 通过。临时 tmpfs 上 pnpm install --lockfile-only --offline --frozen-lockfile --ignore-scripts 通过，容器退出即清理。git diff --check 通过。

尚未完整 Next 构建/浏览器验收。BFF 最新目录安全检查与固定版本重放之间的兼容问题仍待处理，后端完整 PostgreSQL HTTP 验收、兼容发布仍待完成。线上未部署，未重启服务，未修改看板。
