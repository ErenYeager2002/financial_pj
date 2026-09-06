param(
    [ValidateRange(1, 65535)]
    [int]$Port = 3000
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$WebRoot = Join-Path $ProjectRoot 'web'

if (-not (Test-Path -LiteralPath (Join-Path $WebRoot '.next\BUILD_ID'))) {
    throw '缺少生产前端构建目录，请先运行 corepack pnpm --dir web build:webpack。'
}

$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($null -ne $Listener) {
    throw "生产前端端口 $Port 已被占用，请先停止开发前端或其他服务。"
}

$EnvironmentNames = @(
    'NODE_ENV',
    'NEXT_TELEMETRY_DISABLED',
    'NEXT_PUBLIC_APP_URL',
    'FINANCIAL_PLATFORM_API_URL',
    'FINANCIAL_PLATFORM_API_TIMING',
    'PORT',
    'HOSTNAME'
)
$PreviousEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
}

try {
    $env:NODE_ENV = 'production'
    $env:NEXT_TELEMETRY_DISABLED = '1'
    $env:NEXT_PUBLIC_APP_URL = "http://localhost:$Port"
    $env:FINANCIAL_PLATFORM_API_URL = 'http://127.0.0.1:8000'
    $env:FINANCIAL_PLATFORM_API_TIMING = '0'
    $env:PORT = [string]$Port
    $env:HOSTNAME = '127.0.0.1'

    & corepack pnpm --dir $WebRoot start --hostname 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw '生产前端异常退出。'
    }
} finally {
    foreach ($Name in $EnvironmentNames) {
        $Value = $PreviousEnvironment[$Name]
        if ($null -eq $Value) {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -LiteralPath "Env:$Name" -Value $Value
        }
    }
}
