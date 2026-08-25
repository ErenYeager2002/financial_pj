param(
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "deploy\development\compose.yaml"
$DevEnvFile = Join-Path $ProjectRoot "deploy\development\.env"
$DevEnvExample = Join-Path $ProjectRoot "deploy\development\.env.example"
$EnvFile = if (Test-Path -LiteralPath $DevEnvFile) { $DevEnvFile } else { $DevEnvExample }
$ComposeArgs = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile)

$DownArgs = @("down", "--remove-orphans")
if ($RemoveData) {
    $DownArgs += "--volumes"
}

& docker @ComposeArgs @DownArgs
if ($LASTEXITCODE -ne 0) {
    throw "开发环境停止失败。"
}

if ($RemoveData) {
    Write-Host "开发容器和 Docker 数据卷已删除；data\development 目录仍保留。"
} else {
    Write-Host "开发环境已停止，开发数据已保留。"
}

