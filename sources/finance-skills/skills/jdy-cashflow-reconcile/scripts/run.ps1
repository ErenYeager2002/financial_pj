param(
    [Parameter(Mandatory = $true)]
    [string]$DetailPath,

    [Parameter(Mandatory = $true)]
    [string]$MergedPath,

    [string]$OutputPath,
    [string]$PreviewDir,
    [string]$NodeExe = $env:CODEX_NODE_EXE,
    [string]$NodeModulesPath = $env:CODEX_NODE_MODULES
)

$ErrorActionPreference = "Stop"
$skillRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$detail = [System.IO.Path]::GetFullPath($DetailPath)
$merged = [System.IO.Path]::GetFullPath($MergedPath)

if (-not (Test-Path -LiteralPath $detail -PathType Leaf)) {
    throw "基准明细表不存在：$detail"
}
if (-not (Test-Path -LiteralPath $merged -PathType Leaf)) {
    throw "整合表不存在：$merged"
}
if ([System.IO.Path]::GetExtension($merged).ToLowerInvariant() -ne ".xlsx") {
    throw "整合表必须是 .xlsx：$merged"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path (
        [System.IO.Path]::GetDirectoryName($merged)
    ) (
        [System.IO.Path]::GetFileNameWithoutExtension($merged) +
        "_凭证核对标色.xlsx"
    )
}
$output = [System.IO.Path]::GetFullPath($OutputPath)
if ([System.IO.Path]::GetExtension($output).ToLowerInvariant() -ne ".xlsx") {
    throw "输出文件必须是 .xlsx：$output"
}
if ($output -eq $merged -or $output -eq $detail) {
    throw "输出文件不能覆盖输入文件。"
}
if (-not $NodeExe -or -not (Test-Path -LiteralPath $NodeExe -PathType Leaf)) {
    throw "请通过 -NodeExe 提供工作区依赖中的 Node.js 路径。"
}
if (
    -not $NodeModulesPath -or
    -not (Test-Path -LiteralPath $NodeModulesPath -PathType Container)
) {
    throw "请通过 -NodeModulesPath 提供工作区依赖中的 node_modules 路径。"
}

$outputParent = [System.IO.Path]::GetDirectoryName($output)
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$tempDir = Join-Path $outputParent (
    ".jdy-reconcile-" + [Guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $tempDir | Out-Null
$junction = Join-Path $skillRoot "node_modules"
$createdJunction = $false
$detailForNode = $detail

try {
    $detailExtension = [System.IO.Path]::GetExtension($detail).ToLowerInvariant()
    if ($detailExtension -eq ".xls") {
        $detailForNode = Join-Path $tempDir "detail-converted.xlsx"
        $excel = $null
        try {
            $excel = New-Object -ComObject Excel.Application
            $excel.Visible = $false
            $excel.DisplayAlerts = $false
            $book = $excel.Workbooks.Open($detail, 0, $true)
            try {
                $book.SaveAs($detailForNode, 51)
            }
            finally {
                $book.Close($false)
            }
        }
        catch {
            throw "无法通过本机 Excel 转换旧版 .xls：$($_.Exception.Message)"
        }
        finally {
            if ($excel) {
                $excel.Quit()
                [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject(
                    $excel
                ) | Out-Null
            }
        }
    }
    elseif ($detailExtension -ne ".xlsx") {
        throw "基准明细表只支持 .xls 或 .xlsx：$detail"
    }

    if (Test-Path -LiteralPath $junction) {
        $junctionItem = Get-Item -LiteralPath $junction -Force
        if ($junctionItem.LinkType -ne "Junction") {
            throw "Skill 根目录下已存在非 junction 的 node_modules。"
        }
    }
    else {
        New-Item -ItemType Junction -Path $junction -Target $NodeModulesPath |
            Out-Null
        $createdJunction = $true
    }

    $script = Join-Path $PSScriptRoot "reconcile_cashflow.mjs"
    $arguments = @(
        $script,
        "--detail", $detailForNode,
        "--merged", $merged,
        "--output", $output
    )
    if ($PreviewDir) {
        $preview = [System.IO.Path]::GetFullPath($PreviewDir)
        New-Item -ItemType Directory -Path $preview -Force | Out-Null
        $arguments += @("--preview-dir", $preview)
    }

    & $NodeExe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "核对脚本失败，退出码：$LASTEXITCODE"
    }
}
finally {
    if ($createdJunction -and (Test-Path -LiteralPath $junction)) {
        $junctionItem = Get-Item -LiteralPath $junction -Force
        if ($junctionItem.LinkType -eq "Junction") {
            Remove-Item -LiteralPath $junction
        }
    }
    if (Test-Path -LiteralPath $tempDir) {
        $resolvedTemp = (Resolve-Path -LiteralPath $tempDir).Path
        if (
            [System.IO.Path]::GetDirectoryName($resolvedTemp) -ne $outputParent -or
            -not [System.IO.Path]::GetFileName($resolvedTemp).StartsWith(
                ".jdy-reconcile-"
            )
        ) {
            throw "拒绝清理意外的临时目录：$resolvedTemp"
        }
        Remove-Item -LiteralPath $resolvedTemp -Recurse
    }
}
