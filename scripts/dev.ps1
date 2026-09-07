param(
    [switch]$Build,
    [switch]$ValidateOnly,
    [switch]$RestartWorkers,
    [switch]$ResetFrontendCache,
    [switch]$Lan,
    [string]$LanInterfaceAlias = "WLAN",
    [ValidateSet("Local", "Docker")]
    [string]$Frontend = "Local",
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
$HostFrontendScript = Join-Path $ProjectRoot "scripts\dev-frontend-host.ps1"
$HostFrontendStatePath = Join-Path $DevDataDir "frontend-host.json"
$HostFrontendOutputLog = Join-Path $DevDataDir "frontend-host.log"
$HostFrontendErrorLog = Join-Path $DevDataDir "frontend-host-error.log"
$WorkerServices = @(
    "worker-python",
    "worker-http",
    "worker-workflow",
    "worker-task-discovery",
    "worker-agent"
)
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
    $Lines += "FINANCIAL_DEV_AR_HEXIAO_EXECUTION_ENABLED=true"
    $Lines += "FINANCIAL_DEV_TASK_DISCOVERY_ENABLED=true"
    $Lines += "FINANCIAL_AUTH_MODE=session"
    $Lines += "FINANCIAL_TASK_DISCOVERY_HOLIDAYS="
    Set-Content -LiteralPath $DevEnvFile -Value $Lines -Encoding utf8
    Write-Host "已创建开发配置：deploy\development\.env（未复制生产数据）。"
}

function Ensure-DevelopmentPiHarnessToken {
    $Values = Read-EnvValues $DevEnvFile
    if (
        $Values.ContainsKey("FINANCIAL_PI_HARNESS_TOKEN") -and
        -not [string]::IsNullOrWhiteSpace($Values["FINANCIAL_PI_HARNESS_TOKEN"])
    ) {
        return
    }
    $Bytes = New-Object byte[] 48
    $Generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $Generator.GetBytes($Bytes)
    } finally {
        $Generator.Dispose()
    }
    $Token = [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    Add-Content -LiteralPath $DevEnvFile -Value "FINANCIAL_PI_HARNESS_TOKEN=$Token" -Encoding utf8
    Write-Host "已为本机 Pi Harness Worker 生成独立内部令牌（未输出令牌值）。"
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

function Stop-HostFrontend {
    if (Test-Path -LiteralPath $HostFrontendScript) {
        & $HostFrontendScript -Stop
    }
}

function Get-ProcessTree([int]$RootProcessId) {
    $Processes = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId)
    $Ids = [System.Collections.Generic.List[int]]::new()
    $Ids.Add($RootProcessId)
    for ($Index = 0; $Index -lt $Ids.Count; $Index++) {
        $ParentId = $Ids[$Index]
        foreach ($Child in $Processes | Where-Object { $_.ParentProcessId -eq $ParentId }) {
            if (-not $Ids.Contains([int]$Child.ProcessId)) {
                $Ids.Add([int]$Child.ProcessId)
            }
        }
    }
    return @($Ids)
}

function Get-PortListeners([int]$Port) {
    return @(
        Get-NetTCPConnection `
            -LocalPort $Port `
            -State Listen `
            -ErrorAction SilentlyContinue
    )
}

function Test-HostFrontendReady([string]$Origin, [string]$BindHostname) {
    if (-not (Test-Path -LiteralPath $HostFrontendStatePath)) {
        return $false
    }
    try {
        $State = Get-Content -LiteralPath $HostFrontendStatePath -Raw | ConvertFrom-Json
        if (
            [string]$State.project_root -ne $ProjectRoot -or
            [string]$State.app_origin -ne $Origin -or
            [string]$State.hostname -ne $BindHostname
        ) {
            return $false
        }
        $RootProcessId = [int]$State.process_id
        $RootProcess = Get-Process -Id $RootProcessId -ErrorAction SilentlyContinue
        if ($null -eq $RootProcess) {
            return $false
        }
        $RecordedStartTicks = [long]$State.process_start_time_utc_ticks
        if (
            $RecordedStartTicks -le 0 -or
            $RootProcess.StartTime.ToUniversalTime().Ticks -ne $RecordedStartTicks
        ) {
            return $false
        }
        $OwnedProcessIds = @(Get-ProcessTree $RootProcessId)
        $OwnedListener = @(
            Get-PortListeners 3000 |
                Where-Object { $OwnedProcessIds -contains [int]$_.OwningProcess }
        )
        if ($OwnedListener.Count -eq 0) {
            return $false
        }
        $Response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:3000/auth/sign-in" `
            -UseBasicParsing `
            -TimeoutSec 2
        return $Response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Remove-HostFrontendCache {
    $WebRoot = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot "web")).Path.TrimEnd('\')
    $CachePath = Join-Path $WebRoot ".next"
    if (-not (Test-Path -LiteralPath $CachePath)) {
        return
    }
    $ResolvedCache = (Resolve-Path -LiteralPath $CachePath).Path
    if ([IO.Path]::GetDirectoryName($ResolvedCache) -ne $WebRoot) {
        throw "前端缓存目录不在 web 目录内，已拒绝清理：$ResolvedCache"
    }
    Remove-Item -LiteralPath $ResolvedCache -Recurse -Force
    Write-Host "已清理本机前端生成缓存：web\.next"
}

function Start-HostFrontend([string]$Origin, [string]$BindHostname) {
    if (Test-HostFrontendReady -Origin $Origin -BindHostname $BindHostname) {
        Write-Host "本机前端已经运行且配置一致，继续使用现有进程。"
        return
    }
    Stop-HostFrontend
    if (@(Get-PortListeners 3000).Count -gt 0) {
        throw "本机 3000 端口已被其他进程占用，请先停止该服务。"
    }
    Set-Content -LiteralPath $HostFrontendOutputLog -Value "" -Encoding utf8
    Set-Content -LiteralPath $HostFrontendErrorLog -Value "" -Encoding utf8

    $PowerShell = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($null -eq $PowerShell) {
        $PowerShell = Get-Command powershell -ErrorAction Stop
    }
    $Arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $HostFrontendScript,
        "-EnvFile", $DevEnvFile,
        "-AppOrigin", $Origin,
        "-Hostname", $BindHostname
    )
    $Process = Start-Process `
        -FilePath $PowerShell.Source `
        -ArgumentList $Arguments `
        -WindowStyle Hidden `
        -RedirectStandardOutput $HostFrontendOutputLog `
        -RedirectStandardError $HostFrontendErrorLog `
        -PassThru

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
        if ($Process.HasExited) {
            break
        }
        try {
            $OwnedProcessIds = @(Get-ProcessTree $Process.Id)
            $OwnedListener = @(
                Get-PortListeners 3000 |
                    Where-Object { $OwnedProcessIds -contains [int]$_.OwningProcess }
            )
            if ($OwnedListener.Count -eq 0) {
                Start-Sleep -Milliseconds 500
                continue
            }
            $Response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:3000/auth/sign-in" `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($Response.StatusCode -eq 200) {
                $Ready = $true
                break
            }
        } catch {
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $Ready) {
        try {
            Stop-HostFrontend
        } catch {
            Write-Warning "停止未就绪的本机前端时发生异常，将按启动进程树继续清理。"
        } finally {
            $StartedTree = @(Get-ProcessTree $Process.Id)
            [array]::Reverse($StartedTree)
            foreach ($ProcessId in $StartedTree) {
                Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        Write-Host "本机前端输出："
        Get-Content -LiteralPath $HostFrontendOutputLog -Tail 40 -ErrorAction SilentlyContinue
        Get-Content -LiteralPath $HostFrontendErrorLog -Tail 40 -ErrorAction SilentlyContinue
        throw "本机前端未能在规定时间内启动。"
    }
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
Ensure-DevelopmentPiHarnessToken
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
    if ($Frontend -eq "Local") {
        Stop-HostFrontend
        Remove-HostFrontendCache
        & docker @ComposeArgs rm -s -f next
        if ($LASTEXITCODE -ne 0) {
            throw "Docker 前端容器清理失败。"
        }
        $ExistingVolume = & docker volume ls --quiet --filter "name=^${FrontendCacheVolume}$"
        if ($ExistingVolume -eq $FrontendCacheVolume) {
            & docker volume rm $FrontendCacheVolume
            if ($LASTEXITCODE -ne 0) {
                throw "Docker 前端生成缓存清理失败。"
            }
        }
    } else {
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
}

if ($RestartWorkers) {
    & docker @ComposeArgs up -d --force-recreate @WorkerServices
    if ($LASTEXITCODE -ne 0) {
        throw "开发 Worker 重启失败。"
    }
    & docker @ComposeArgs ps @WorkerServices
    return
}

if ($Build) {
    & docker @ComposeArgs build api worker-agent
    if ($LASTEXITCODE -ne 0) {
        throw "开发后端基础镜像构建失败。"
    }
}

$UpArgs = @("up", "-d", "--remove-orphans")
if ($Build) {
    $UpArgs += "--force-recreate"
}
if ($Frontend -eq "Local") {
    & docker @ComposeArgs stop next
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 前端停止失败。"
    }
    $UpArgs += "api"
    if ($Mode -eq "Tasks") {
        $UpArgs += $WorkerServices
    }
} else {
    Stop-HostFrontend
}
& docker @ComposeArgs @UpArgs
if ($LASTEXITCODE -ne 0) {
    throw "开发环境启动失败。"
}

if ($Frontend -eq "Local") {
    $FrontendOrigin = if ($Lan) { "http://${LanAddress}:3000" } else { "http://localhost:3000" }
    $FrontendHostname = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
    Start-HostFrontend -Origin $FrontendOrigin -BindHostname $FrontendHostname
}

& docker @ComposeArgs ps
if ($LASTEXITCODE -ne 0) {
    throw "开发环境状态检查失败。"
}

Write-Host "开发平台：http://localhost:3000"
Write-Host "开发 API：http://localhost:8000/api/health"
if ($Frontend -eq "Local") {
    Write-Host "前端模式：Windows 本机 Turbopack；日志：data\development\frontend-host.log"
} else {
    Write-Host "前端模式：Docker Webpack"
}
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
Write-Host "API 和前端保留热更新；任务 Worker 不随源码保存重启。确认无活动任务后，使用 .\scripts\dev.ps1 -RestartWorkers 加载 Worker 修改；依赖或 Dockerfile 修改后运行 .\scripts\dev.ps1 -Build。"
