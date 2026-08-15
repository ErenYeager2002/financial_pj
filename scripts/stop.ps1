$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "deploy\production\compose.yaml"
$EnvFile = Join-Path $ProjectRoot "deploy\production\.env"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "缺少生产环境配置：$EnvFile"
}

& docker compose --env-file $EnvFile -f $ComposeFile stop
if ($LASTEXITCODE -ne 0) {
    throw "平台停止失败。"
}
