param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourcePath = Join-Path $ProjectRoot "tools\windows-launcher\FinancialPlatformLauncher.cs"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $ProjectRoot "启动财务Skill平台.exe"
} elseif (-not [IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path $ProjectRoot $OutputPath
}

$CompilerCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
)
$Compiler = $CompilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($null -eq $Compiler) {
    throw "未找到 Windows .NET Framework C# 编译器。"
}
if (-not (Test-Path -LiteralPath $SourcePath)) {
    throw "缺少启动器源码：$SourcePath"
}

$OutputDirectory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}

& $Compiler `
    /nologo `
    /target:winexe `
    /optimize+ `
    "/out:$OutputPath" `
    /reference:System.dll `
    /reference:System.Drawing.dll `
    /reference:System.Windows.Forms.dll `
    $SourcePath
if ($LASTEXITCODE -ne 0) {
    throw "启动器编译失败。"
}

Write-Host "启动器已生成：$OutputPath"
