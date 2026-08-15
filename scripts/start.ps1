param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "deploy\production\compose.yaml"
$EnvFile = Join-Path $ProjectRoot "deploy\production\.env"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "缺少生产环境配置。请先运行 .\.venv\Scripts\python.exe scripts\prepare_production_env.py。"
}

$ComposeArgs = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile)
if ($Build) {
    & docker @ComposeArgs build
    if ($LASTEXITCODE -ne 0) {
        throw "容器镜像构建失败。"
    }
}

& docker @ComposeArgs up -d
if ($LASTEXITCODE -ne 0) {
    throw "平台启动失败。"
}

& docker @ComposeArgs ps
if ($LASTEXITCODE -ne 0) {
    throw "平台状态检查失败。"
}

Write-Host "平台地址：https://localhost:8443"
