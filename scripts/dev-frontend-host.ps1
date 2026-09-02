param(
    [switch]$Stop,
    [string]$EnvFile,
    [string]$AppOrigin = "http://localhost:3000",
    [string]$Hostname = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$WebRoot = Join-Path $ProjectRoot "web"
$AgentRuntimeRoot = Join-Path $ProjectRoot "agent-runtime"
$StatePath = Join-Path $ProjectRoot "data\development\frontend-host.json"
$ScriptPath = $MyInvocation.MyCommand.Path

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

function Get-ProcessTree([int]$RootProcessId) {
    $Processes = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, CommandLine)
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

function Stop-HostFrontend {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return
    }
    try {
        $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        $RootProcessId = [int]$State.process_id
        $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $RootProcessId" -ErrorAction SilentlyContinue
        if ($null -ne $Process) {
            $LiveProcess = Get-Process -Id $RootProcessId -ErrorAction SilentlyContinue
            $ExpectedScript = [IO.Path]::GetFileName($ScriptPath)
            $CommandLine = if ($null -eq $Process.CommandLine) { "" } else { $Process.CommandLine }
            $StateProjectRoot = [string]$State.project_root
            $SameProject = (
                -not [string]::IsNullOrWhiteSpace($StateProjectRoot) -and
                [IO.Path]::GetFullPath($StateProjectRoot).TrimEnd('\') -eq $ProjectRoot.TrimEnd('\')
            )
            $RecordedStartTicks = if ($null -ne $State.process_start_time_utc_ticks) {
                [long]$State.process_start_time_utc_ticks
            } else {
                0
            }
            $SameProcessInstance = (
                $RecordedStartTicks -gt 0 -and
                $null -ne $LiveProcess -and
                $LiveProcess.StartTime.ToUniversalTime().Ticks -eq $RecordedStartTicks
            )
            $LegacyCommandMatch = (
                $RecordedStartTicks -eq 0 -and
                $CommandLine -like "*$ExpectedScript*"
            )
            if (-not $SameProject -or (-not $SameProcessInstance -and -not $LegacyCommandMatch)) {
                Write-Warning "PID $RootProcessId 已由其他进程使用，已清理过期的前端状态；未停止该进程。"
                return
            }
            $Tree = @(Get-ProcessTree $RootProcessId)
            [array]::Reverse($Tree)
            foreach ($ProcessId in $Tree) {
                Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    } finally {
        Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    }
}

function Get-DependencyFingerprint([string]$Directory) {
    $PackageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Directory "package.json")).Hash
    $LockHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Directory "pnpm-lock.yaml")).Hash
    $Bytes = [Text.Encoding]::UTF8.GetBytes("$PackageHash`n$LockHash")
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $Hash = $Hasher.ComputeHash($Bytes)
        return -join ($Hash | ForEach-Object { $_.ToString("x2") })
    } finally {
        $Hasher.Dispose()
    }
}

function Ensure-Dependencies(
    [string]$Directory,
    [string]$ExpectedBinary,
    [switch]$IgnoreScripts
) {
    $NodeModules = Join-Path $Directory "node_modules"
    $Stamp = Join-Path $NodeModules ".financial-platform-dependencies.sha256"
    $InstalledLock = Join-Path $NodeModules ".pnpm\lock.yaml"
    $ProjectLock = Join-Path $Directory "pnpm-lock.yaml"
    $Fingerprint = Get-DependencyFingerprint $Directory
    $InstallRequired = -not (Test-Path -LiteralPath $ExpectedBinary)

    if (-not $InstallRequired -and (Test-Path -LiteralPath $Stamp)) {
        $InstallRequired = (Get-Content -LiteralPath $Stamp -Raw).Trim() -ne $Fingerprint
    } elseif (-not $InstallRequired) {
        $InstallRequired = (
            -not (Test-Path -LiteralPath $InstalledLock) -or
            (Get-FileHash -Algorithm SHA256 -LiteralPath $InstalledLock).Hash -ne
                (Get-FileHash -Algorithm SHA256 -LiteralPath $ProjectLock).Hash
        )
    }

    if ($InstallRequired) {
        Write-Host "依赖发生变化，正在安装：$Directory"
        $Arguments = @("pnpm", "--dir", $Directory, "install", "--frozen-lockfile")
        if ($IgnoreScripts) {
            $Arguments += "--ignore-scripts"
        }
        & corepack @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "依赖安装失败：$Directory"
        }
    } else {
        Write-Host "依赖未变化，跳过安装：$Directory"
    }

    New-Item -ItemType Directory -Path $NodeModules -Force | Out-Null
    Set-Content -LiteralPath $Stamp -Value $Fingerprint -Encoding ascii
}

function Ensure-AgentRuntimeModuleCopy {
    $NodeModulesRoot = Join-Path $WebRoot "node_modules"
    $ScopeRoot = Join-Path $NodeModulesRoot "@financial-platform"
    $ModulePath = Join-Path $ScopeRoot "agent-runtime"
    $RuntimePackage = Join-Path $AgentRuntimeRoot "package.json"
    $RuntimeDist = Join-Path $AgentRuntimeRoot "dist"
    $RuntimeEntry = Join-Path $RuntimeDist "index.js"
    if (-not (Test-Path -LiteralPath $RuntimeEntry)) {
        throw "Agent Runtime 构建产物不存在：$RuntimeEntry"
    }

    New-Item -ItemType Directory -Path $ScopeRoot -Force | Out-Null
    if (Test-Path -LiteralPath $ModulePath) {
        $Module = Get-Item -LiteralPath $ModulePath -Force
        $ExpectedParent = [IO.Path]::GetFullPath($ScopeRoot).TrimEnd('\')
        $ActualParent = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ModulePath)).TrimEnd('\')
        if ($ActualParent -ne $ExpectedParent) {
            throw "Agent Runtime 模块路径不在前端依赖目录内，拒绝替换：$ModulePath"
        }
        if ($Module.LinkType -in @("Junction", "SymbolicLink")) {
            [IO.Directory]::Delete($ModulePath, $false)
        } else {
            Remove-Item -LiteralPath $ModulePath -Recurse -Force
        }
    }

    New-Item -ItemType Directory -Path $ModulePath -Force | Out-Null
    Copy-Item -LiteralPath $RuntimePackage -Destination $ModulePath
    Copy-Item -LiteralPath $RuntimeDist -Destination $ModulePath -Recurse
}

if ($Stop) {
    Stop-HostFrontend
    return
}

if ([string]::IsNullOrWhiteSpace($EnvFile) -or -not (Test-Path -LiteralPath $EnvFile)) {
    throw "缺少开发环境配置文件。"
}

New-Item -ItemType Directory -Path (Split-Path -Parent $StatePath) -Force | Out-Null
$CurrentProcess = Get-Process -Id $PID
@{
    app_origin = $AppOrigin
    hostname = $Hostname
    process_id = $PID
    process_start_time_utc_ticks = $CurrentProcess.StartTime.ToUniversalTime().Ticks
    project_root = $ProjectRoot
    started_at = [DateTimeOffset]::Now.ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding utf8

$Values = Read-EnvValues $EnvFile
$ForwardedKeys = @(
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    "CLERK_SECRET_KEY",
    "FINANCIAL_AUTH_MODE",
    "FINANCIAL_SESSION_COOKIE",
    "AGENT_RUNTIME",
    "AGENT_RUNTIME_PI_USERS",
    "AGENT_RUNTIME_FALLBACK"
)
foreach ($Key in $ForwardedKeys) {
    Remove-Item -LiteralPath "Env:$Key" -ErrorAction SilentlyContinue
}
$env:NODE_ENV = "development"
$env:NEXT_TELEMETRY_DISABLED = "1"
$env:NEXT_PUBLIC_SENTRY_DISABLED = "true"
$env:HUSKY = "0"
$env:CI = "true"
$env:COREPACK_DEFAULT_TO_LATEST = "0"

$RuntimeWatch = $null
try {
    & corepack prepare pnpm@10.15.1 --activate
    if ($LASTEXITCODE -ne 0) {
        throw "pnpm 版本准备失败。"
    }

    Ensure-Dependencies `
        -Directory $AgentRuntimeRoot `
        -ExpectedBinary (Join-Path $AgentRuntimeRoot "node_modules\.bin\tsc.cmd") `
        -IgnoreScripts

    & corepack pnpm --dir $AgentRuntimeRoot run build
    if ($LASTEXITCODE -ne 0) {
        throw "Agent Runtime 构建失败。"
    }

    Ensure-Dependencies `
        -Directory $WebRoot `
        -ExpectedBinary (Join-Path $WebRoot "node_modules\.bin\next.cmd")
    Ensure-AgentRuntimeModuleCopy

    foreach ($Key in $ForwardedKeys) {
        if ($Values.ContainsKey($Key)) {
            Set-Item -LiteralPath "Env:$Key" -Value $Values[$Key]
        }
    }
    $env:NEXT_PUBLIC_APP_URL = $AppOrigin
    $env:FINANCIAL_PLATFORM_API_URL = "http://127.0.0.1:8000"
    $env:PORT = "3000"
    $env:HOSTNAME = $Hostname

    $RuntimeWatch = Start-Process `
        -FilePath (Get-Command corepack.cmd).Source `
        -ArgumentList @("pnpm", "--dir", $AgentRuntimeRoot, "exec", "tsc", "-p", "tsconfig.json", "--watch") `
        -PassThru `
        -NoNewWindow

    & corepack pnpm --dir $WebRoot dev --hostname $Hostname
    if ($LASTEXITCODE -ne 0) {
        throw "本机 Next.js 开发服务异常退出。"
    }
} finally {
    if ($null -ne $RuntimeWatch -and -not $RuntimeWatch.HasExited) {
        $RuntimeTree = @(Get-ProcessTree $RuntimeWatch.Id)
        [array]::Reverse($RuntimeTree)
        foreach ($ProcessId in $RuntimeTree) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
}
