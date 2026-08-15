---
name: jdy-cashflow-export
description: 使用 Selenium 接管带远程调试端口的 Microsoft Edge，自动登录金蝶精斗云/金蝶AI星辰，进入财务报表中的现金流量表，按最大期间查询并逐项处理“本期金额”，在现金流量调整列表中选择本年、查询、全选并导出明细。用户要求金蝶现金流量表、本期金额、现金流量调整列表、批量导出、RPA 查账，或排查这套导出流程时使用。
---

# 金蝶现金流量明细导出

## 执行原则

使用本 Skill 附带的确定性脚本完成浏览器操作，不临时拼写浏览器点击代码。默认新建运行标签页并清理旧金蝶页面，避免从错误页面继续执行。

只执行登录、导航、查询、勾选和导出。不得点击“全部重算”“批量调整”“批量调整选中行”“自动指定”“重新指定”“不指定”等会修改财务数据的操作。

不得在终端、回复、提交记录或诊断文件名中输出账号、密码和具体财务数据。

## 运行流程

1. 将 Skill 根目录记为 `SKILL_DIR`。
2. 确认 Python 环境已安装 `requirements.txt` 中的依赖。
3. 运行 `scripts/start_edge.ps1`，启动带远程调试端口的 Edge。
4. 确认凭据来自以下任一安全来源：
   - 环境变量 `JDY_USERNAME` 与 `JDY_PASSWORD`；
   - 被 Git 忽略的 `工作区/rpa/jdy_credentials.local.json`；
   - 终端交互输入。
5. 运行 `python scripts/run.py`。
6. 根据终端输出核验候选行数、导出数、跳过数、失败数和导出目录。

Windows PowerShell 示例：

```powershell
Set-Location $SKILL_DIR
python -m pip install -r .\requirements.txt
.\scripts\start_edge.ps1
python .\scripts\run.py
```

只验证登录：

```powershell
python .\scripts\run.py --login-only
```

只处理前一行以做小范围端到端验证：

```powershell
python .\scripts\run.py --max-rows 1
```

需要人工勾选协议和点击登录时，追加 `--manual-login`。除非用户明确要求复用当前标签页，否则不要使用 `--use-current-tab`。

## 判断完成

只有检测到“进入使用”按钮才算真正登录成功；登录页和登录后工作台可能共享相似 URL，不能只根据 URL 判断。

现金流量表只处理“本期金额”，不得改成“本月金额”。扫描虚拟滚动表格后按 `data-row-key` 去重；有金额但三秒内未打开调整列表的行记为跳过，不记为导出。

每个成功行都必须满足：

1. 调整列表期间为本年，即第 1 期至第 12 期。
2. 已点击查询。
3. 第一个 `input.kd-checkbox-input` 对应的全选状态已生效。
4. 已点击文字为“导出”的导出控件。
5. 下载目录出现完整文件，不只依赖点击成功。

## 故障处理

先读取 [references/workflow.md](references/workflow.md) 核对流程状态，再读取 [references/selectors.md](references/selectors.md) 核对页面定位器。优先保留失败截图并报告失败行号、阶段和异常类型，不输出业务明细。

页面结构变化时，只修改 `scripts/jdy_selenium_rpa.py` 中对应定位器，并运行 `python -m unittest discover -s tests -v` 与 Skill 校验器。涉及会计数据写入的新按钮一律停止并请求用户确认。
