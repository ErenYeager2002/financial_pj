param(
    [int]$Port = 8000,
    [string]$HostAddress = "127.0.0.1",
    [string]$LanInterfaceAlias = "WLAN",
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

$Arguments = @(
    "$PSScriptRoot\serve_control.py",
    "start",
    "--port",
    $Port,
    "--host",
    $HostAddress
)
if ($NoBrowser) {
    $Arguments += "--no-browser"
}

& $Python @Arguments
$ExitCode = $LASTEXITCODE
if ($ExitCode -eq 0 -and $HostAddress -in @("0.0.0.0", "::")) {
    $LanAddress = Get-NetIPAddress `
        -InterfaceAlias $LanInterfaceAlias `
        -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($LanAddress) {
        Write-Host "局域网访问地址：http://${LanAddress}:$Port"
    }
}
exit $ExitCode
