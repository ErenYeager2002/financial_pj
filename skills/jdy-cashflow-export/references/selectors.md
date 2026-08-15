# 页面定位器

定位器按优先级排列。页面改版时先更新精确定位器，再保留语义后备定位器。

## 官网与登录

| 目标 | 首选定位器 | 后备判断 |
|---|---|---|
| 我的工作台 | `.workstation.btn-green` | 文本包含“我的工作台” |
| 官网登录 | `a[href="/login"]`、`a[href="/login/"]`、`a.toplogin` | 可见登录入口 |
| 用户名 | `#login_username` | name/id/placeholder 含 user、account、用户名、账号、手机号 |
| 密码 | `#login_pwd` | `input[type="password"]` 或 name/id/placeholder 含 password、pwd、密码 |
| 协议 | `#reg_agreement` | 登录表单内可见 checkbox |
| 提交登录 | `#login_btn_gray` | 登录表单内文字为“登录”的可见按钮 |
| 登录完成 | 文本为“进入使用”的可见按钮 | 不使用 URL 代替 |
| 平衡检查提示 | 文本精确为“我知道了” | 仅关闭提示，不点击任何重算入口 |

## 财务报表

| 目标 | 判断 |
|---|---|
| 现金流量表 | 页面或 iframe 内文本“现金流量表” |
| 目标金额列 | 表头精确包含“本期金额” |
| 虚拟滚动容器 | class 包含 `kd-table-body` |
| 行身份 | `data-row-key` |
| 有效金额 | 支持逗号、小数、负数和括号负数的金额文本 |

不得用“本月金额”替代“本期金额”。

## 现金流量调整列表

| 目标 | 首选定位器 | 状态确认 |
|---|---|---|
| 期间 | 文本“本年” | 显示第 1 期至第 12 期 |
| 查询 | 文字精确为“查询”的按钮 | 出现 `input.kd-checkbox-input` |
| 全选 | 第一个 `input.kd-checkbox-input` | checked/is_selected 或“已选中 N 条”且 N > 0 |
| 导出 | `._2zTfwwd5._3PwtlkVv` 或 `span._3PwtlkVv` 中文字精确为“导出” | 下载目录出现完整文件 |

同一 class 可能对应多个控件。全选始终使用列表中的第一个 `input.kd-checkbox-input`，导出必须再用可见文本“导出”过滤，不能只按 class 盲点。
