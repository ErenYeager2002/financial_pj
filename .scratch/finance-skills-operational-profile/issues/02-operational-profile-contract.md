# 02 — 运行画像契约

Status: ready-for-human

在 Registry 建立深模块接口，统一校验执行类型、外部数据来源和员工标签。

Blocked by: 01

- [x] 模型约束和网络一致性校验完成。
- [x] 员工接口只返回脱敏标签。
- [x] 管理员 Manifest 保留完整运行画像。
- [x] 公共接口测试先红后绿。

## Comments

运行画像由 Registry 统一校验；员工 DTO 只公开 `operation_labels`，完整画像保留在 Manifest 管理边界。
