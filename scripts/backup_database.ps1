# 财务 Skill 平台备份脚本。
# 用法：
#   .\scripts\backup_database.ps1                  # 默认标签 migration
#   .\scripts\backup_database.ps1 -Label scheduled # 指定用途标签
#   .\scripts\backup_database.ps1 -IncludeKeys      # 另含高敏凭据恢复包
param(
    [string]$Label = "migration",
    [switch]$IncludeKeys
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "没有找到项目虚拟环境，请先运行 scripts\bootstrap.ps1。"
}

$Arguments = @((Join-Path $PSScriptRoot "backup_database.py"), "--label", $Label)
if ($IncludeKeys) {
    $Arguments += "--include-keys"
}
& $Python @Arguments
exit $LASTEXITCODE
