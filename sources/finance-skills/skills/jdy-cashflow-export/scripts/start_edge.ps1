param(
    [int]$Port = 9222,
    [string]$UserDataDir = (
        Join-Path $PSScriptRoot "..\工作区\rpa\selenium-edge-profile"
    )
)

$edgeCandidates = @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
$edgePath = $edgeCandidates |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1

if (-not $edgePath) {
    throw "没有找到 Microsoft Edge。"
}

$versionUrl = "http://127.0.0.1:$Port/json/version"
try {
    $null = Invoke-RestMethod -Uri $versionUrl -TimeoutSec 2
    Write-Host "Edge 远程调试端口已开启：$Port"
    exit 0
}
catch {
    # 尚未启动，继续。
}

$profilePath = if ([System.IO.Path]::IsPathRooted($UserDataDir)) {
    [System.IO.Path]::GetFullPath($UserDataDir)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $UserDataDir))
}
New-Item -ItemType Directory -Path $profilePath -Force | Out-Null

$arguments = @(
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=$Port",
    "--user-data-dir=$profilePath",
    "http://www.jdy.com/"
)
Start-Process -FilePath $edgePath -ArgumentList $arguments

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        $version = Invoke-RestMethod -Uri $versionUrl -TimeoutSec 2
        Write-Host "Edge 已启动，远程调试地址：127.0.0.1:$Port"
        Write-Host "浏览器版本：$($version.Browser)"
        exit 0
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

throw "Edge 已启动，但 30 秒内没有检测到远程调试端口 $Port。"
