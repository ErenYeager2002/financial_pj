param(
    [switch]$Build,
    [switch]$ValidateOnly,
    [switch]$RestartWorkers,
    [switch]$ResetFrontendCache,
    [switch]$Lan,
    [string]$LanInterfaceAlias = "WLAN",
    [ValidateSet("Core", "Tasks")]
    [string]$Mode = "Core"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "deploy\development\compose.yaml"
$LanComposeFile = Join-Path $ProjectRoot "deploy\development\compose.lan.yaml"
$DevEnvFile = Join-Path $ProjectRoot "deploy\development\.env"
$DevEnvExample = Join-Path $ProjectRoot "deploy\development\.env.example"
$ProductionEnvFile = Join-Path $ProjectRoot "deploy\production\.env"
$DevDataDir = Join-Path $ProjectRoot "data\development"
$WorkerServices = @("worker-python", "worker-http", "worker-workflow", "worker-task-discovery")
$FrontendCacheVolume = "financial-platform-dev_next-cache"

function Get-PythonCommand {
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $Python) {
        throw "未找到 Python。请安装 Python 3.11+ 或创建项目 .venv。"
    }
    return $Python.Source
}

function Read-EnvValues([string]$Path) {
    $Values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $Values
    }
    foreach ($Line in Get-Content -LiteralPath $Path) {
        if ($Line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $Values[$Matches[1]] = $Matches[2]
        }
    }
    return $Values
}

function Initialize-DevelopmentEnv {
    if (Test-Path -LiteralPath $DevEnvFile) {
        return
    }

    $SourceValues = Read-EnvValues $ProductionEnvFile
    $Keys = @(
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        "CLERK_SECRET_KEY",
        "FINANCIAL_AUTH_MODE",
        "FINANCIAL_CLERK_ISSUER",
        "FINANCIAL_NETWORK_POLICY_MODE",
        "FINANCIAL_EGRESS_PROXY_TARGETS",
        "FINANCIAL_EGRESS_PROXY_ALLOWLIST",
        "FINANCIAL_ZHIYUN_BASE_URL",
        "AGENT_RUNTIME",
        "AGENT_RUNTIME_PI_USERS",
        "AGENT_RUNTIME_FALLBACK"
    )
    $Lines = @(
        "# 本机开发配置；由 scripts/dev.ps1 初始化，不得提交 Git。",
        "POSTGRES_PASSWORD=financial-dev-local-only"
    )
    foreach ($Key in $Keys) {
        $Value = if ($SourceValues.ContainsKey($Key)) { $SourceValues[$Key] } else { "" }
        $Lines += "${Key}=${Value}"
    }
    $Lines += "FINANCIAL_DEV_AR_HEXIAO_EXECUTION_ENABLED=false"
    $Lines += "FINANCIAL_DEV_TASK_DISCOVERY_ENABLED=false"
    $Lines += "FINANCIAL_TASK_DISCOVERY_HOLIDAYS="
    Set-Content -LiteralPath $DevEnvFile -Value $Lines -Encoding utf8
    Write-Host "已创建开发配置：deploy\development\.env（未复制生产数据）。"
}

function Assert-DevelopmentCredentials {
    $Values = Read-EnvValues $DevEnvFile
    $AuthMode = if ($Values.ContainsKey("FINANCIAL_AUTH_MODE")) {
        $Values["FINANCIAL_AUTH_MODE"]
    } else {
        "clerk"
    }
    if ($AuthMode -notin @("session", "clerk", "hybrid")) {
        throw "FINANCIAL_AUTH_MODE 只能是 session、clerk 或 hybrid。"
    }
    if ($AuthMode -in @("clerk", "hybrid")) {
        foreach ($Key in @("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "CLERK_SECRET_KEY", "FINANCIAL_CLERK_ISSUER")) {
            if (-not $Values.ContainsKey($Key) -or [string]::IsNullOrWhiteSpace($Values[$Key])) {
                throw "当前认证模式缺少 Clerk 配置：$Key。"
            }
        }
    }
}

function Resolve-LanAddress([string]$InterfaceAlias) {
    $Addresses = @(
        Get-NetIPAddress `
            -InterfaceAlias $InterfaceAlias `
            -AddressFamily IPv4 `
            -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike "169.254.*" -and $_.IPAddress -ne "127.0.0.1" }
    )
    if ($Addresses.Count -eq 0) {
        throw "接口 $InterfaceAlias 没有可用的局域网 IPv4 地址。"
    }
    if ($Addresses.Count -gt 1) {
        Write-Warning "接口 $InterfaceAlias 有多个 IPv4 地址，将使用 $($Addresses[0].IPAddress)。"
    }
    return $Addresses[0].IPAddress
}

$Python = Get-PythonCommand
& $Python (Join-Path $ProjectRoot "scripts\validate_development_mode.py")
if ($LASTEXITCODE -ne 0) {
    throw "开发模式配置校验失败。"
}

$ConfigEnvFile = if (Test-Path -LiteralPath $DevEnvFile) { $DevEnvFile } else { $DevEnvExample }
$ComposeArgs = @("compose", "--env-file", $ConfigEnvFile, "-f", $ComposeFile)
& docker @ComposeArgs config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "开发 Compose 配置无效。"
}

if ($ValidateOnly) {
    Write-Host "开发模式配置校验通过。"
    return
}

Initialize-DevelopmentEnv
Assert-DevelopmentCredentials
$LanAddress = ""
if ($Lan) {
    if (-not (Test-Path -LiteralPath $LanComposeFile)) {
        throw "缺少局域网开发 Compose 覆盖配置：$LanComposeFile"
    }
    $LanAddress = Resolve-LanAddress $LanInterfaceAlias
    $env:FINANCIAL_LAN_ORIGIN = "http://${LanAddress}:3000"
}
New-Item -ItemType Directory -Path $DevDataDir -Force | Out-Null
$ComposeArgs = @("compose", "--env-file", $DevEnvFile, "-f", $ComposeFile)
if ($Lan) {
    $ComposeArgs += @("-f", $LanComposeFile)
}
if ($Mode -eq "Tasks" -or $RestartWorkers) {
    $ComposeArgs += @("--profile", "tasks")
}

if ($ResetFrontendCache) {
    & docker @ComposeArgs rm -s -f next
    if ($LASTEXITCODE -ne 0) {
        throw "开发前端容器清理失败。"
    }
    $ExistingVolume = & docker volume ls --quiet --filter "name=^${FrontendCacheVolume}$"
    if ($ExistingVolume -eq $FrontendCacheVolume) {
        & docker volume rm $FrontendCacheVolume
        if ($LASTEXITCODE -ne 0) {
            throw "开发前端缓存卷清理失败。"
        }
    }
    & docker @ComposeArgs up -d next
    if ($LASTEXITCODE -ne 0) {
        throw "开发前端重新启动失败。"
    }
    & docker @ComposeArgs ps next
    return
}

if ($RestartWorkers) {
    & docker @ComposeArgs up -d @WorkerServices
    if ($LASTEXITCODE -ne 0) {
        throw "开发 Worker 重启失败。"
    }
    & docker @ComposeArgs ps @WorkerServices
    return
}

if ($Build) {
    & docker @ComposeArgs build api
    if ($LASTEXITCODE -ne 0) {
        throw "开发后端基础镜像构建失败。"
    }
}

$UpArgs = @("up", "-d", "--remove-orphans")
if ($Build) {
    $UpArgs += "--force-recreate"
}
& docker @ComposeArgs @UpArgs
if ($LASTEXITCODE -ne 0) {
    throw "开发环境启动失败。"
}

& docker @ComposeArgs ps
if ($LASTEXITCODE -ne 0) {
    throw "开发环境状态检查失败。"
}

Write-Host "开发平台：http://localhost:3000"
Write-Host "开发 API：http://localhost:8000/api/health"
if ($Lan) {
    Write-Host "局域网平台：http://${LanAddress}:3000"
    Write-Host "局域网 API 健康检查：http://${LanAddress}:8000/api/health"
    Write-Host "请确认 Windows 防火墙只允许专用网络的 LocalSubnet 访问 3000 和 8000 端口。"
}
if ($Mode -eq "Tasks") {
    Write-Host "任务 Worker 与受控外联代理已启动。"
} else {
    Write-Host "当前为 Core 模式；执行任务时使用 .\scripts\dev.ps1 -Mode Tasks。"
}
Write-Host "API 和前端普通源码修改会自动更新；任务 Worker 使用稳定进程，修改 Worker 或 Skill 后重启任务模式，依赖或 Dockerfile 修改后运行 .\scripts\dev.ps1 -Build。"
