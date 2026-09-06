param(
    [switch]$Stop,
    [ValidateRange(1, 65535)]
    [int]$Port = 3001
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$HostScript = Join-Path $ProjectRoot 'scripts\dev-frontend-host.ps1'
$EnvFile = Join-Path $ProjectRoot 'deploy\development\.env'
$StatePath = Join-Path $ProjectRoot 'data\development\frontend-hot.json'
$HotDistDir = '.next-hot'

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw '缺少开发环境配置，请先运行 .\scripts\dev.ps1。'
}

$Arguments = @(
    '-EnvFile', $EnvFile,
    '-AppOrigin', "http://localhost:$Port",
    '-Hostname', '127.0.0.1',
    '-Port', $Port,
    '-StatePathOverride', $StatePath
)
if ($Stop) {
    $Arguments = @('-Stop', '-StatePathOverride', $StatePath)
}

$PreviousDistDir = $env:NEXT_DIST_DIR
try {
    if (-not $Stop) {
        $env:NEXT_DIST_DIR = $HotDistDir
    }
    & $HostScript @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "本机热更新前端异常退出。"
    }
} finally {
    if ($null -eq $PreviousDistDir) {
        Remove-Item Env:NEXT_DIST_DIR -ErrorAction SilentlyContinue
    } else {
        $env:NEXT_DIST_DIR = $PreviousDistDir
    }
}
