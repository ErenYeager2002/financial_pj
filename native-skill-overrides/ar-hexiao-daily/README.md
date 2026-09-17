# 应收核销独立 Skill 包

版本：2026.09.16.1。把整个ar-hexiao-daily目录交给支持读取SKILL.md和运行Python脚本的AI工具；从SKILL.md开始。安装目录依工具而定，本包不自动安装到已有同名Skill或平台。

Python 3.11及以上。基础依赖：`python -m pip install -r requirements.txt`。联网取数另安装 `requirements-browser.txt`，按所选浏览器入口安装浏览器驱动或运行 `python -m playwright install chromium`。基础依赖固定为当前运行环境版本；浏览器可选依赖另列，当前打包验证不代表已在新机器成功登录。

离线使用时提供本次智云完整导出、每年度一份盈亏表及一份到账流转表。联网使用时由所在网络连接智云，并从环境/凭据库提供认证。包内无凭据、用户工作簿、生产数据库、导出材料或历史任务台账。到账名称对照配置已置为空列表，请提供自己的明确名称对照表。

`python scripts/check_package.py` 校验完整性。VERSION.json记录代码来源和源文件SHA-256，SHA256SUMS.json覆盖全部发布文件。解压到可写位置，在包目录外建立业务工作区；命令始终显式传入--workspace及年度映射。

本包保留当前业务逻辑与已修复模块，并提供AI执行说明；不包含平台Web服务。原平台和本机已有同名Skill未被替换。已知历史依赖及运行边界见references/current-behavior.md。

文件路径包含空格或特殊字符时用引号包围整个参数值。命令中的占位符必须替换后执行，不要原样复制尖括号。
