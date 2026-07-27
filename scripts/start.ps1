param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Frontend = Join-Path $ProjectRoot "frontend\dist\index.html"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "没有找到项目虚拟环境，请先运行 scripts\bootstrap.ps1。"
}
if (-not (Test-Path -LiteralPath $Frontend)) {
    throw "前端尚未构建，请先运行 scripts\bootstrap.ps1。"
}

$Arguments = @("$PSScriptRoot\serve_control.py", "start", "--port", $Port)
if ($NoBrowser) {
    $Arguments += "--no-browser"
}

& $Python @Arguments
exit $LASTEXITCODE
