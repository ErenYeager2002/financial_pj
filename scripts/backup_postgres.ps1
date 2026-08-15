param(
    [string]$BackupRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeFile = Join-Path $projectRoot "deploy\production\compose.yaml"
$envFile = Join-Path $projectRoot "deploy\production\.env"
if (-not $BackupRoot) {
    $BackupRoot = Join-Path $projectRoot "data\backups"
}

function Read-DotEnvValue([string]$Name, [string]$DefaultValue = "") {
    $line = Get-Content -LiteralPath $envFile | Where-Object {
        $_ -match "^$([regex]::Escape($Name))="
    } | Select-Object -Last 1
    if (-not $line) {
        if ($DefaultValue) {
            return $DefaultValue
        }
        throw "生产环境文件缺少 $Name。"
    }
    return ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
}

function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 命令执行失败。"
    }
}

$databaseUser = Read-DotEnvValue "POSTGRES_USER" "financial"
$databaseName = Read-DotEnvValue "POSTGRES_DB" "financial"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $BackupRoot "${stamp}_postgres-verified"
$dumpName = "financial-platform-${stamp}.dump"
$dumpPath = Join-Path $backupDir $dumpName
$containerDump = "/tmp/$dumpName"
$restoreDatabase = "${databaseName}_restore_verify_$stamp"
$postgresId = (& docker compose --env-file $envFile -f $composeFile ps -q postgres).Trim()
$apiId = (& docker compose --env-file $envFile -f $composeFile ps -q api).Trim()
if (-not $postgresId -or -not $apiId) {
    throw "PostgreSQL 或 API 容器未运行。"
}

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
try {
    Invoke-Docker @("exec", $postgresId, "pg_dump", "-U", $databaseUser, "-d", $databaseName, "-Fc", "--no-owner", "--no-privileges", "-f", $containerDump)
    Invoke-Docker @("cp", "${postgresId}:$containerDump", $dumpPath)
    Invoke-Docker @("exec", $postgresId, "dropdb", "--if-exists", "--force", "-U", $databaseUser, $restoreDatabase)
    Invoke-Docker @("exec", $postgresId, "createdb", "-U", $databaseUser, $restoreDatabase)
    Invoke-Docker @("exec", $postgresId, "pg_restore", "-U", $databaseUser, "-d", $restoreDatabase, "--no-owner", "--no-privileges", $containerDump)

    $comparisonScript = Get-Content -Raw -LiteralPath (Join-Path $projectRoot "scripts\verify_postgres_restore.py")
    $comparisonJson = $comparisonScript | & docker exec -i $apiId python - --target-database $restoreDatabase
    if ($LASTEXITCODE -ne 0) {
        throw "恢复数据比对失败。"
    }
    $comparison = $comparisonJson | ConvertFrom-Json
    if (-not $comparison.verified) {
        throw "恢复数据比对未通过。"
    }

    $dumpFile = Get-Item -LiteralPath $dumpPath
    $report = [ordered]@{
        created_at = (Get-Date).ToString("o")
        backup_file = $dumpFile.Name
        size_bytes = $dumpFile.Length
        sha256 = (Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
        restore_verified = [bool]$comparison.verified
        revision = $comparison.revision
        tables = [int]$comparison.table_count
        rows = [int]$comparison.row_count
        failed_tables = @($comparison.failed_tables)
    }
    $reportPath = Join-Path $backupDir "verification.json"
    [IO.File]::WriteAllText(
        $reportPath,
        ($report | ConvertTo-Json -Depth 5),
        [Text.UTF8Encoding]::new($false)
    )
    $report | ConvertTo-Json -Compress
}
finally {
    & docker exec $postgresId dropdb --if-exists --force -U $databaseUser $restoreDatabase 2>$null
    & docker exec $postgresId rm -f $containerDump 2>$null
}
