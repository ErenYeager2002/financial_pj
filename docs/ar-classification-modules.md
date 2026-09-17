# 应收核销判定模块

正式版和极速版的 `vendor/scripts/classify_hexiao.py` 保留命令行及原导入名称，只负责兼容入口。两个版本保留各自的读取实现，不能整目录互相覆盖。任务仍固定创建时的 Skill 快照，新版本不改写旧任务快照。

| 模块 | 职责 |
| --- | --- |
| classification_contract | 错误类型、金额容差 |
| classification_exports | 读取智云导出、跨日期记录归属及去重 |
| classification_amounts | 到账总额、本币金额、币种及金额工具 |
| classification_parent_allocation | 无逐单金额时的父回款分配 |
| classification_expansion | SO/SOD 展开及来源覆盖校验 |
| classification_ledger | 当前盈亏表只读索引、行定位及已有回款匹配 |
| classification_decision | 单笔核销判定与写入字段计划 |
| classification_splitting | 多笔回款拆行链、SOD 顺序承接 |
| classification_accrual | 整个 SO 的结清和计提判断 |
| classification_summary | 三类结果汇总及序列化 |
| classification_runner | 串联单笔判定、批内依赖和年度路由 |
| classification_cli | 参数处理、取数与结果文件编排 |

依赖从命令入口到批次编排、业务判定、只读索引及金额工具。业务模块不依赖兼容入口；已有独立回款校验模块在运行时使用兼容导入，以保留既有调用方式。

当前工作簿与本次智云明细决定写入计划。历史差异只作辅助说明，不能单独否决订单。平台初始化时重新核对历史已写事件与当前文件；确实不在当前文件的记录退出已写集合，原记录保留追溯。不能证明对应关系的记录仍由当前表的身份、金额、写前校验和写后回读检查处理。

结构回归使用各版本的 `python -m unittest discover -p "test_*.py" -q`。注入分笔链失败的测试现在作用于 `classification_runner` 的调用边界，保留同组五条记录全部挂起的断言。拆分前后各业务函数的语法树逐项对比，保证结构迁移未悄悄改变判断。
