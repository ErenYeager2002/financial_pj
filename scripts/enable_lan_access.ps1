param(
    [int]$Port = 8000,
    [string]$InterfaceAlias = "WLAN",
    [string]$AllowedRemoteAddress = "LocalSubnet"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
$IsAdministrator = $Principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $IsAdministrator) {
    Write-Host "正在请求管理员权限，请在 Windows 提示中点击“是”。"
    $Arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Port", $Port,
        "-InterfaceAlias", "`"$InterfaceAlias`"",
        "-AllowedRemoteAddress", "`"$AllowedRemoteAddress`""
    )
    Start-Process powershell.exe -Verb RunAs -ArgumentList $Arguments
    exit 0
}

$Profile = Get-NetConnectionProfile -InterfaceAlias $InterfaceAlias
if (-not $Profile) {
    throw "没有找到网络接口：$InterfaceAlias"
}

if ($Profile.NetworkCategory -ne "Private") {
    Set-NetConnectionProfile `
        -InterfaceAlias $InterfaceAlias `
        -NetworkCategory Private
    Write-Host "已将 $InterfaceAlias 网络设置为“专用网络”。"
}

$RuleName = "Finance Skills LAN $Port"
$Rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue |
    Select-Object -First 1

if ($Rule) {
    Set-NetFirewallRule `
        -InputObject $Rule `
        -Enabled True `
        -Profile Private `
        -Direction Inbound `
        -Action Allow `
        -InterfaceAlias $InterfaceAlias `
        -RemoteAddress $AllowedRemoteAddress | Out-Null
    $Rule |
        Get-NetFirewallPortFilter |
        Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port | Out-Null
    Write-Host "已更新防火墙规则：$RuleName"
}
else {
    New-NetFirewallRule `
        -DisplayName $RuleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Port `
        -Profile Private `
        -InterfaceAlias $InterfaceAlias `
        -RemoteAddress $AllowedRemoteAddress | Out-Null
    Write-Host "已创建防火墙规则：$RuleName"
}

$LanAddress = Get-NetIPAddress `
    -InterfaceAlias $InterfaceAlias `
    -AddressFamily IPv4 `
    -ErrorAction Stop |
    Where-Object { $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress

Write-Host ""
Write-Host "局域网访问已启用："
Write-Host "http://${LanAddress}:$Port"
Write-Host ""
Write-Host "入站接口：$InterfaceAlias"
Write-Host "允许来源：$AllowedRemoteAddress"
