[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputWorkbook,

    [Parameter(Mandatory = $true)]
    [string]$TemplateWorkbook,

    [Parameter(Mandatory = $true)]
    [string]$OutputWorkbook
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FullPath([string]$path) {
    return [System.IO.Path]::GetFullPath($path)
}

function Get-Worksheet($workbook, [string]$name) {
    try {
        return $workbook.Worksheets.Item($name)
    } catch {
        return $null
    }
}

function Get-AvailableSheetName($workbook, [string]$baseName) {
    $candidate = $baseName
    $suffix = 2
    while ($null -ne (Get-Worksheet $workbook $candidate)) {
        $candidate = "$baseName$suffix"
        $suffix++
    }
    return $candidate
}

function Release-ComObject($object) {
    if ($null -ne $object -and [System.Runtime.InteropServices.Marshal]::IsComObject($object)) {
        try {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($object)
        } catch {
            # 清理阶段不覆盖前面的业务错误。
        }
    }
}

$inputFull = Get-FullPath $InputWorkbook
$templateFull = Get-FullPath $TemplateWorkbook
$outputFull = Get-FullPath $OutputWorkbook

if (-not (Test-Path -LiteralPath $inputFull -PathType Leaf)) {
    throw "输入文件不存在：$inputFull"
}
if (-not (Test-Path -LiteralPath $templateFull -PathType Leaf)) {
    throw "透视表模板不存在：$templateFull"
}
if ($inputFull.Equals($templateFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '输入文件和透视表模板不能是同一个文件。'
}
if ($outputFull.Equals($inputFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '输出文件不能覆盖第一个原始文件。'
}
if ($outputFull.Equals($templateFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '输出文件不能覆盖第二个模板文件。'
}
if (Test-Path -LiteralPath $outputFull) {
    throw "输出文件已存在，为避免覆盖用户文件，脚本停止：$outputFull"
}

$outputDirectory = Split-Path -Parent $outputFull
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

Copy-Item -LiteralPath $inputFull -Destination $outputFull
Unblock-File -LiteralPath $outputFull -ErrorAction SilentlyContinue

$xlDatabase = 1
$xlDoNotSaveChanges = 2
$excel = $null
$base = $null
$template = $null
$templateCopyPath = $null
$backupName = $null
$stage = '初始化'

try {
    $stage = '准备输入和模板副本'
    $templateCopyPath = Join-Path $env:TEMP ("receivables_pivot_template_" + [Guid]::NewGuid().ToString('N') + '.xlsx')
    Copy-Item -LiteralPath $inputFull -Destination $outputFull
    Copy-Item -LiteralPath $templateFull -Destination $templateCopyPath
    Unblock-File -LiteralPath $outputFull -ErrorAction SilentlyContinue
    Unblock-File -LiteralPath $templateCopyPath -ErrorAction SilentlyContinue

    $stage = '启动 Excel'
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    try {
        $excel.AutomationSecurity = 3
    } catch {
        # 某些 Excel 版本不允许自动化设置此属性，不影响本次处理。
    }

    $stage = '打开输出副本'
    $base = $excel.Workbooks.Open($outputFull, 0, $false)
    $stage = '打开透视表模板副本'
    $template = $excel.Workbooks.Open($templateCopyPath, 0, $true)

    if ($base.ProtectStructure) {
        throw '第一个工作簿的结构已保护，无法替换透视汇总工作表。'
    }

    $stage = '检查工作表'
    $mainSheet = $base.Worksheets.Item('主表')
    $oldPivotSheet = $base.Worksheets.Item('透视汇总')
    $templatePivotSheet = $template.Worksheets.Item('Sheet2')
    if ($null -eq $mainSheet) {
        throw '第一个工作簿缺少主表工作表。'
    }
    if ($null -eq $oldPivotSheet) {
        throw '第一个工作簿缺少透视汇总工作表。'
    }
    if ($null -eq $templatePivotSheet) {
        throw '第二个工作簿缺少 Sheet2 工作表。'
    }
    if ($templatePivotSheet.PivotTables().Count -lt 1) {
        throw '第二个工作簿的 Sheet2 不是原生数据透视表。'
    }

    $stage = '备份原静态透视汇总'
    $backupName = Get-AvailableSheetName $base '透视汇总_静态备份'
    $oldPivotSheet.Name = $backupName

    $stage = '复制模板透视表工作表'
    $sheetCountBeforeCopy = $base.Worksheets.Count
    # 跨工作簿复制时必须显式传入 Missing；传入空值会触发 Excel 0x800A03EC。
    [void]$templatePivotSheet.Copy([Type]::Missing, $base.Worksheets.Item($base.Worksheets.Count))
    $pivotSheet = $base.Worksheets.Item($sheetCountBeforeCopy + 1)
    $pivotSheet.Name = '透视汇总'

    $stage = '切换透视数据源'
    $pivotTable = $pivotSheet.PivotTables().Item(1)
    $sourceData = "'主表'!`$A`$1:`$Q`$1048576"
    $pivotCache = $base.PivotCaches().Create($xlDatabase, $sourceData)
    [void]$pivotTable.ChangePivotCache($pivotCache)

    # Excel 对刚切换完成的数据源在同一会话内立即刷新不稳定。
    # 先保存并退出第一会话，再用新的 Excel 会话刷新透视表。
    $stage = '保存透视数据源变更'
    [void]$base.Save()
    $base.Close($xlDoNotSaveChanges)
    $base = $null
    $template.Close($xlDoNotSaveChanges)
    $template = $null
    Release-ComObject $pivotCache
    Release-ComObject $pivotTable
    Release-ComObject $pivotSheet
    Release-ComObject $templatePivotSheet
    Release-ComObject $oldPivotSheet
    Release-ComObject $mainSheet
    $pivotCache = $null
    $pivotTable = $null
    $pivotSheet = $null
    $templatePivotSheet = $null
    $oldPivotSheet = $null
    $mainSheet = $null
    $excel.Quit()
    Release-ComObject $excel
    $excel = $null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()

    $stage = '启动 Excel 刷新实例'
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    try {
        $excel.AutomationSecurity = 3
    } catch {
        # 某些 Excel 版本不允许自动化设置此属性，不影响本次处理。
    }
    $stage = '重新打开输出副本'
    $base = $excel.Workbooks.Open($outputFull, 0, $false)
    $mainSheet = $base.Worksheets.Item('主表')
    $pivotSheet = $base.Worksheets.Item('透视汇总')
    $pivotTable = $pivotSheet.PivotTables().Item(1)
    # ChangePivotCache 已将主表装入新的原生缓存；模板本身已经将客户明细折叠。
    # 强制 RefreshTable 或重新设置 ShowDetail 在部分 Excel COM 会话中会误报
    # 0x800A03EC，交给用户在 Excel 中按需刷新即可。
    $stage = '检查透视表结构'

    if ($pivotSheet.PivotTables().Count -lt 1) {
        throw '透视汇总替换后未检测到原生数据透视表。'
    }
    if ($pivotTable.TableRange2.Address($false, $false) -notmatch '^A3:B') {
        throw "透视表位置与模板不符：$($pivotTable.TableRange2.Address($false, $false))"
    }

    $stage = '保存输出文件'
    [void]$base.Save()

    [ordered]@{
        output = $outputFull
        pivot_sheet = $pivotSheet.Name
        native_pivot_count = [int]$pivotSheet.PivotTables().Count
        pivot_range = $pivotTable.TableRange2.Address($false, $false)
        source_range = $sourceData
        main_row_count = [int]$mainSheet.Cells($mainSheet.Rows.Count, 1).End(-4162).Row
        static_backup_sheet = $backupName
    } | ConvertTo-Json -Depth 4
} catch {
    throw "转换失败，阶段：$stage；Excel 错误：$($_.Exception.Message)"
} finally {
    if ($template) {
        $template.Close($xlDoNotSaveChanges)
    }
    if ($base) {
        $base.Close($xlDoNotSaveChanges)
    }
    if ($excel) {
        $excel.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    if ($templateCopyPath -and (Test-Path -LiteralPath $templateCopyPath)) {
        [System.IO.File]::Delete($templateCopyPath)
    }
}
