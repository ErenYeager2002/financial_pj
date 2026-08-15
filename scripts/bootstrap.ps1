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

# 数据库备份与版本化迁移：既有数据库先备份，再由应用统一入口识别并接管旧库。
if (Test-Path -LiteralPath (Join-Path $ProjectRoot "data\financial.db")) {
    & $VenvPython (Join-Path $PSScriptRoot "backup_database.py") --label bootstrap
    if ($LASTEXITCODE -ne 0) {
        throw "数据库备份失败，已停止迁移。"
    }
}
Push-Location (Join-Path $ProjectRoot "backend")
try {
    & $VenvPython -c "from app.database import init_db; init_db()"
    if ($LASTEXITCODE -ne 0) {
        throw "数据库迁移失败，请查看迁移输出。"
    }
}
finally {
    Pop-Location
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
