param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$WebRoot = Join-Path $ProjectRoot "web"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $PythonCommand -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        throw "Python 虚拟环境创建失败。"
    }
}

& $VenvPython -m pip install -e "$ProjectRoot\backend[dev]" `
    -i "https://pypi.tuna.tsinghua.edu.cn/simple"
if ($LASTEXITCODE -ne 0) {
    throw "Python 依赖安装失败。"
}

Push-Location $WebRoot
try {
    corepack prepare pnpm@10.15.1 --activate
    corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) {
        throw "Next.js 依赖安装失败。"
    }
}
finally {
    Pop-Location
}

Write-Host "开发依赖已安装。生产部署请运行 scripts\start.ps1。"
