param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $PythonCommand -m venv (Join-Path $ProjectRoot ".venv")
}

& $VenvPython -m pip install -e "$ProjectRoot\backend[dev]" `
    -i "https://pypi.tuna.tsinghua.edu.cn/simple"
if ($LASTEXITCODE -ne 0) {
    throw "Python 依赖安装失败。"
}

Push-Location (Join-Path $ProjectRoot "frontend")
try {
    npm install --proxy=null --https-proxy=null `
        --registry="https://registry.npmmirror.com"
    if ($LASTEXITCODE -ne 0) {
        throw "前端依赖安装失败。"
    }
    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "前端构建失败。"
    }
}
finally {
    Pop-Location
}

Write-Host "初始化完成。运行 scripts\start.ps1 启动平台。"
