import fs from "node:fs/promises";
import path from "node:path";

import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

import {
  addGroup,
  compareGroups,
  normalizeProject,
  normalizeVoucher,
  numberValue,
} from "./reconciliation_core.mjs";

const REQUIRED_MERGED_HEADERS = [
  "来源文件批次",
  "日期",
  "凭证字号",
  "摘要",
  "科目",
  "辅助核算",
  "借方金额",
  "贷方金额",
  "现金流量项目",
  "流入金额",
  "流出金额",
];

const REQUIRED_DETAIL_HEADERS = ["凭证号", "现金流量项目", "方向", "金额"];

const STATUS_PRIORITY = new Map([
  ["金额及笔数不符", 1],
  ["金额不符", 2],
  ["笔数不符", 3],
  ["整合表缺失", 4],
  ["明细表无此凭证", 5],
  ["核对一致", 6],
]);

const STATUS_COLORS = new Map([
  ["金额及笔数不符", "#F4CCCC"],
  ["金额不符", "#FCE5CD"],
  ["笔数不符", "#FFF2CC"],
  ["整合表缺失", "#D9D2E9"],
  ["明细表无此凭证", "#D9D2E9"],
]);

function parseArgs(argv) {
  const options = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) {
      throw new Error(`无法识别的参数：${token}`);
    }
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`参数缺少值：${token}`);
    }
    options.set(token, value);
    index += 1;
  }
  for (const required of ["--detail", "--merged", "--output"]) {
    if (!options.has(required)) {
      throw new Error(`缺少必需参数：${required}`);
    }
  }
  return {
    detailPath: path.resolve(options.get("--detail")),
    mergedPath: path.resolve(options.get("--merged")),
    outputPath: path.resolve(options.get("--output")),
    previewDir: options.has("--preview-dir")
      ? path.resolve(options.get("--preview-dir"))
      : null,
  };
}

function text(value) {
  return String(value ?? "").trim();
}

function locateHeader(values, requiredHeaders, maxRows = 30) {
  const limit = Math.min(maxRows, values.length);
  for (let rowIndex = 0; rowIndex < limit; rowIndex += 1) {
    const row = values[rowIndex].map(text);
    const indexes = new Map();
    for (const header of requiredHeaders) {
      const columnIndex = row.indexOf(header);
      if (columnIndex < 0) {
        break;
      }
      indexes.set(header, columnIndex);
    }
    if (indexes.size === requiredHeaders.length) {
      return { rowIndex, indexes, headers: row };
    }
  }
  throw new Error(`未找到表头：${requiredHeaders.join("、")}`);
}

function groupKey(project, voucher) {
  return `${project}\u001f${voucher}`;
}

function worksheetOrNull(workbook, name) {
  try {
    return workbook.worksheets.getItem(name);
  } catch {
    return null;
  }
}

function excelColumn(columnNumber) {
  let value = columnNumber;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function setHeaderStyle(range) {
  range.format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#9EADBA" },
  };
}

function setTitleStyle(range) {
  range.format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF", size: 16 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
}

function applyStatusFormatting(range, statusColumnLetter, firstDataRow) {
  for (const [status, color] of STATUS_COLORS) {
    range.conditionalFormats.addCustom(
      `=$${statusColumnLetter}${firstDataRow}="${status}"`,
      { fill: color },
    );
  }
}

function buildDetailGroups(values, header) {
  const groups = new Map();
  let dataRows = 0;
  for (let rowIndex = header.rowIndex + 1; rowIndex < values.length; rowIndex += 1) {
    const row = values[rowIndex];
    const originalVoucher = text(row[header.indexes.get("凭证号")]);
    const originalProject = text(row[header.indexes.get("现金流量项目")]);
    if (!originalVoucher && !originalProject) {
      continue;
    }
    const project = normalizeProject(originalProject);
    const voucher = normalizeVoucher(originalVoucher);
    if (!project) {
      continue;
    }
    const amount = numberValue(row[header.indexes.get("金额")]);
    addGroup(groups, project, voucher, amount, originalVoucher);
    dataRows += 1;
  }
  return { groups, dataRows };
}

function buildMergedGroups(values, header) {
  const groups = new Map();
  const rows = [];
  for (let rowIndex = header.rowIndex + 1; rowIndex < values.length; rowIndex += 1) {
    const row = values[rowIndex];
    const originalVoucher = text(row[header.indexes.get("凭证字号")]);
    const originalProject = text(row[header.indexes.get("现金流量项目")]);
    if (!originalVoucher && !originalProject) {
      rows.push(null);
      continue;
    }
    const project = normalizeProject(originalProject);
    const voucher = normalizeVoucher(originalVoucher);
    if (!project) {
      rows.push(null);
      continue;
    }
    const amount =
      numberValue(row[header.indexes.get("流入金额")]) +
      numberValue(row[header.indexes.get("流出金额")]);
    addGroup(groups, project, voucher, amount, originalVoucher);
    rows.push({ key: groupKey(project, voucher), project, voucher });
  }
  return { groups, rows };
}

function statusCount(statusCounts, status) {
  return statusCounts[status] ?? 0;
}

async function savePreview(workbook, options, outputPath) {
  const blob = await workbook.render(options);
  await fs.writeFile(outputPath, new Uint8Array(await blob.arrayBuffer()));
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.detailPath === options.outputPath || options.mergedPath === options.outputPath) {
    throw new Error("输出文件不能覆盖输入文件。");
  }

  const [detailBlob, mergedBlob] = await Promise.all([
    FileBlob.load(options.detailPath),
    FileBlob.load(options.mergedPath),
  ]);
  const [detailWorkbook, workbook] = await Promise.all([
    SpreadsheetFile.importXlsx(detailBlob),
    SpreadsheetFile.importXlsx(mergedBlob),
  ]);

  const detailSheet = detailWorkbook.worksheets.getItemAt(0);
  const detailValues = detailSheet.getUsedRange(true).values;
  const detailHeader = locateHeader(detailValues, REQUIRED_DETAIL_HEADERS);
  const { groups: detailGroups, dataRows: detailRowCount } = buildDetailGroups(
    detailValues,
    detailHeader,
  );

  const mergedSheet = worksheetOrNull(workbook, "合并明细");
  if (!mergedSheet) {
    throw new Error("整合表缺少“合并明细”工作表。");
  }
  if (worksheetOrNull(workbook, "核对汇总")) {
    throw new Error("整合表已包含“核对汇总”，请改用未标色的原始合并表。");
  }

  const mergedUsedRange = mergedSheet.getUsedRange(true);
  const mergedValues = mergedUsedRange.values;
  const mergedHeader = locateHeader(mergedValues, REQUIRED_MERGED_HEADERS);
  if (
    mergedHeader.headers.includes("规范凭证号") ||
    mergedHeader.headers.includes("核对结果")
  ) {
    throw new Error("整合表已包含核对列，请改用未标色的原始合并表。");
  }
  for (let index = 0; index < REQUIRED_MERGED_HEADERS.length; index += 1) {
    if (mergedHeader.headers[index] !== REQUIRED_MERGED_HEADERS[index]) {
      throw new Error("“合并明细”的原始列顺序与预期不一致，已停止以免标错列。");
    }
  }

  const { groups: mergedGroups, rows: mergedRows } = buildMergedGroups(
    mergedValues,
    mergedHeader,
  );
  const { comparisons, statusCounts } = compareGroups(detailGroups, mergedGroups);
  const mismatchGroups = [...comparisons.values()].filter(
    (item) => item.status !== "核对一致",
  );

  const detailProjects = new Set([...detailGroups.values()].map((item) => item.project));
  const mergedProjects = new Set([...mergedGroups.values()].map((item) => item.project));
  const detailOnlyProjects = [...detailProjects]
    .filter((item) => !mergedProjects.has(item))
    .sort();
  const mergedOnlyProjects = [...mergedProjects]
    .filter((item) => !detailProjects.has(item))
    .sort();

  const headerRow = mergedHeader.rowIndex + 1;
  const firstDataRow = headerRow + 1;
  const lastDataRow = headerRow + mergedRows.length;
  const appendedHeaders = [
    "规范凭证号",
    "核对结果",
    "基准笔数",
    "整合笔数",
    "基准金额",
    "整合金额",
    "差额（整合-基准）",
  ];
  const appendedValues = mergedRows.map((row) => {
    if (!row) {
      return ["", "", "", "", "", "", ""];
    }
    const result = comparisons.get(row.key);
    return [
      row.voucher,
      result.status,
      result.detailCount,
      result.mergedCount,
      result.detailTotal,
      result.mergedTotal,
      null,
    ];
  });

  for (const table of [...mergedSheet.tables.items]) {
    table.delete();
  }
  try {
    mergedSheet.unmergeCells("A1:R3");
  } catch {
    // The source can legitimately contain no merges in this area.
  }
  mergedSheet.mergeCells("A1:R1");
  mergedSheet.getRange("A1").values = [["现金流量调整明细合并表（凭证核对）"]];
  setTitleStyle(mergedSheet.getRange("A1:R1"));
  mergedSheet.getRange("A1:R1").format.rowHeight = 30;

  mergedSheet.getRange("L2:P2").values = [[
    "异常凭证组",
    mismatchGroups.length,
    "核对一致组",
    statusCount(statusCounts, "核对一致"),
    "核对口径",
  ]];
  mergedSheet.mergeCells("Q2:R2");
  mergedSheet.getRange("Q2").values = [["项目 + 规范凭证号；金额误差 < 0.005"]];
  mergedSheet.getRange("L2:R2").format = {
    fill: "#D9EAF7",
    font: { bold: true, color: "#17365D" },
    verticalAlignment: "center",
    wrapText: true,
  };
  mergedSheet.getRange("L2:R2").format.rowHeight = 28;
  mergedSheet.getRange("M2:O2").format.horizontalAlignment = "center";
  mergedSheet.getRange("M2:O2").format.numberFormat = "#,##0";

  const legendItems = [
    ["A3:B3", "金额及笔数不符", "#F4CCCC"],
    ["C3:D3", "金额不符", "#FCE5CD"],
    ["E3:F3", "笔数不符", "#FFF2CC"],
    ["G3:H3", "整合表缺失 / 明细表无此凭证", "#D9D2E9"],
    ["I3:R3", "红橙黄紫均需复核；“核对一致”不着色", "#EAF2F8"],
  ];
  for (const [address, label, fill] of legendItems) {
    mergedSheet.mergeCells(address);
    const range = mergedSheet.getRange(address);
    range.values = [[label]];
    range.format = {
      fill,
      font: { bold: true, color: "#273746" },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      wrapText: true,
    };
  }
  mergedSheet.getRange("A3:R3").format.rowHeight = 24;

  mergedSheet.getRange(`L${headerRow}:R${headerRow}`).values = [appendedHeaders];
  setHeaderStyle(mergedSheet.getRange(`A${headerRow}:R${headerRow}`));
  mergedSheet.getRange(`A${headerRow}:R${headerRow}`).format.rowHeight = 32;
  if (mergedRows.length > 0) {
    mergedSheet.getRange(`L${firstDataRow}:R${lastDataRow}`).values = appendedValues;
    mergedSheet.getRange(`R${firstDataRow}`).formulas = [[
      `=Q${firstDataRow}-P${firstDataRow}`,
    ]];
    if (lastDataRow > firstDataRow) {
      mergedSheet.getRange(`R${firstDataRow}:R${lastDataRow}`).fillDown();
    }
    mergedSheet.getRange(`G${firstDataRow}:H${lastDataRow}`).format.numberFormat =
      "#,##0.00;[Red]-#,##0.00";
    mergedSheet.getRange(`J${firstDataRow}:K${lastDataRow}`).format.numberFormat =
      "#,##0.00;[Red]-#,##0.00";
    mergedSheet.getRange(`O${firstDataRow}:R${lastDataRow}`).format.numberFormat =
      "#,##0.00;[Red]-#,##0.00";
    mergedSheet.getRange(`N${firstDataRow}:O${lastDataRow}`).format.numberFormat =
      "#,##0";
    applyStatusFormatting(
      mergedSheet.getRange(`A${firstDataRow}:R${lastDataRow}`),
      "M",
      firstDataRow,
    );
  }

  mergedSheet.tables.add(
    `A${headerRow}:R${Math.max(headerRow, lastDataRow)}`,
    true,
    "CashflowReconcileDetails",
  ).style = "TableStyleMedium2";
  mergedSheet.freezePanes.freezeRows(headerRow);
  mergedSheet.freezePanes.freezeColumns(3);
  mergedSheet.showGridLines = false;
  const widths = {
    A: 16,
    B: 13,
    C: 13,
    D: 34,
    E: 28,
    F: 34,
    G: 15,
    H: 15,
    I: 34,
    J: 15,
    K: 15,
    L: 14,
    M: 18,
    N: 12,
    O: 12,
    P: 16,
    Q: 16,
    R: 18,
  };
  for (const [column, width] of Object.entries(widths)) {
    mergedSheet.getRange(`${column}:${column}`).format.columnWidth = width;
  }
  mergedSheet.getRange(`A${firstDataRow}:R${lastDataRow}`).format.verticalAlignment =
    "center";
  mergedSheet.getRange(`D${firstDataRow}:F${lastDataRow}`).format.wrapText = true;
  mergedSheet.getRange(`I${firstDataRow}:I${lastDataRow}`).format.wrapText = true;

  const summarySheet = workbook.worksheets.add("核对汇总");
  summarySheet.showGridLines = false;
  summarySheet.mergeCells("A1:J1");
  summarySheet.getRange("A1").values = [["现金流量项目 × 凭证号核对汇总"]];
  setTitleStyle(summarySheet.getRange("A1:J1"));
  summarySheet.getRange("A1:J1").format.rowHeight = 30;
  summarySheet.getRange("A2:H2").values = [[
    "基准凭证组",
    detailGroups.size,
    "整合凭证组",
    mergedGroups.size,
    "核对一致组",
    statusCount(statusCounts, "核对一致"),
    "异常凭证组",
    mismatchGroups.length,
  ]];
  summarySheet.getRange("A2:H2").format = {
    fill: "#D9EAF7",
    font: { bold: true, color: "#17365D" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  summarySheet.mergeCells("A3:J3");
  summarySheet.getRange("A3").values = [[
    "判定：现金流量项目别名归一后，与去除数字前导零的凭证号共同分组；整合金额=流入金额+流出金额。",
  ]];
  summarySheet.getRange("A3:J3").format = {
    fill: "#EAF2F8",
    font: { color: "#273746" },
    verticalAlignment: "center",
    wrapText: true,
  };
  summarySheet.getRange("A3:J3").format.rowHeight = 28;

  const summaryHeaders = [
    "现金流量项目（规范）",
    "规范凭证号",
    "基准凭证号",
    "整合凭证号",
    "核对结果",
    "基准笔数",
    "整合笔数",
    "基准金额",
    "整合金额",
    "差额（整合-基准）",
  ];
  const summaryHeaderRow = 5;
  const summaryFirstDataRow = 6;
  const sortedMismatches = mismatchGroups.sort((left, right) => {
    return (
      (STATUS_PRIORITY.get(left.status) ?? 99) -
        (STATUS_PRIORITY.get(right.status) ?? 99) ||
      left.project.localeCompare(right.project, "zh-CN") ||
      left.voucher.localeCompare(right.voucher, "zh-CN", { numeric: true })
    );
  });
  const summaryValues = sortedMismatches.map((result) => [
    result.project,
    result.voucher,
    result.detailOriginalVouchers,
    result.mergedOriginalVouchers,
    result.status,
    result.detailCount,
    result.mergedCount,
    result.detailTotal,
    result.mergedTotal,
    null,
  ]);
  summarySheet.getRange(`A${summaryHeaderRow}:J${summaryHeaderRow}`).values = [
    summaryHeaders,
  ];
  setHeaderStyle(summarySheet.getRange(`A${summaryHeaderRow}:J${summaryHeaderRow}`));
  summarySheet.getRange(`A${summaryHeaderRow}:J${summaryHeaderRow}`).format.rowHeight =
    32;
  const summaryLastDataRow =
    summaryValues.length > 0
      ? summaryFirstDataRow + summaryValues.length - 1
      : summaryHeaderRow;
  if (summaryValues.length > 0) {
    summarySheet.getRange(
      `A${summaryFirstDataRow}:J${summaryLastDataRow}`,
    ).values = summaryValues;
    summarySheet.getRange(`J${summaryFirstDataRow}`).formulas = [[
      `=I${summaryFirstDataRow}-H${summaryFirstDataRow}`,
    ]];
    if (summaryLastDataRow > summaryFirstDataRow) {
      summarySheet
        .getRange(`J${summaryFirstDataRow}:J${summaryLastDataRow}`)
        .fillDown();
    }
    summarySheet.getRange(
      `F${summaryFirstDataRow}:G${summaryLastDataRow}`,
    ).format.numberFormat = "#,##0";
    summarySheet.getRange(
      `H${summaryFirstDataRow}:J${summaryLastDataRow}`,
    ).format.numberFormat = "#,##0.00;[Red]-#,##0.00";
    applyStatusFormatting(
      summarySheet.getRange(`A${summaryFirstDataRow}:J${summaryLastDataRow}`),
      "E",
      summaryFirstDataRow,
    );
  }
  summarySheet.tables.add(
    `A${summaryHeaderRow}:J${summaryLastDataRow}`,
    true,
    "CashflowReconcileSummary",
  ).style = "TableStyleMedium2";
  summarySheet.freezePanes.freezeRows(summaryHeaderRow);
  summarySheet.freezePanes.freezeColumns(2);
  const summaryWidths = [36, 14, 18, 18, 20, 12, 12, 16, 16, 19];
  summaryWidths.forEach((width, index) => {
    const column = excelColumn(index + 1);
    summarySheet.getRange(`${column}:${column}`).format.columnWidth = width;
  });
  if (summaryValues.length > 0) {
    summarySheet.getRange(
      `A${summaryFirstDataRow}:E${summaryLastDataRow}`,
    ).format.wrapText = true;
    summarySheet.getRange(
      `A${summaryFirstDataRow}:J${summaryLastDataRow}`,
    ).format.verticalAlignment = "center";
  }

  await workbook.inspect({
    kind: "table",
    range: `合并明细!L${headerRow}:R${Math.min(lastDataRow, firstDataRow + 7)}`,
    include: "values,formulas",
    tableMaxRows: 10,
    tableMaxCols: 7,
    maxChars: 3000,
  });
  await workbook.inspect({
    kind: "table",
    range: `核对汇总!A1:J${Math.min(summaryLastDataRow, 14)}`,
    include: "values,formulas",
    tableMaxRows: 14,
    tableMaxCols: 10,
    maxChars: 5000,
  });
  const errorScan = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
  });
  if (!errorScan.ndjson.includes("matched 0 entries")) {
    throw new Error("公式错误扫描未通过，请检查生成的核对工作簿。");
  }

  if (options.previewDir) {
    await fs.mkdir(options.previewDir, { recursive: true });
    await savePreview(
      workbook,
      {
        sheetName: "合并明细",
        range: `A1:R${Math.min(lastDataRow, 20)}`,
        scale: 1.4,
        format: "png",
      },
      path.join(options.previewDir, "detail-top.png"),
    );
    await savePreview(
      workbook,
      {
        sheetName: "核对汇总",
        range: `A1:J${Math.min(summaryLastDataRow, 28)}`,
        scale: 1.4,
        format: "png",
      },
      path.join(options.previewDir, "summary.png"),
    );
    const firstMergedMismatchIndex = mergedRows.findIndex((row) => {
      return row && comparisons.get(row.key)?.status !== "核对一致";
    });
    if (firstMergedMismatchIndex >= 0) {
      const mismatchRow = firstDataRow + firstMergedMismatchIndex;
      await savePreview(
        workbook,
        {
          sheetName: "合并明细",
          range: `A${Math.max(firstDataRow, mismatchRow - 2)}:R${Math.min(
            lastDataRow,
            mismatchRow + 2,
          )}`,
          scale: 1.4,
          format: "png",
        },
        path.join(options.previewDir, "first-mismatch.png"),
      );
    }
  }

  await fs.mkdir(path.dirname(options.outputPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(options.outputPath);
  await fs.rm(`${options.outputPath}.inspect.ndjson`, { force: true });

  const report = {
    output: options.outputPath,
    detailRows: detailRowCount,
    mergedRows: mergedRows.filter(Boolean).length,
    detailGroups: detailGroups.size,
    mergedGroups: mergedGroups.size,
    matchedGroups: statusCount(statusCounts, "核对一致"),
    mismatchGroups: mismatchGroups.length,
    statusCounts,
    detailOnlyProjects,
    mergedOnlyProjects,
  };
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`核对失败：${error.message}\n`);
  process.exitCode = 1;
});
