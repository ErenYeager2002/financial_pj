export const PROJECT_ALIASES = new Map([
  ["收到的其他与经营活动的现金", "收到其他与经营活动有关的现金"],
  ["支付的与其他经营活动有关的现金", "支付其他与经营活动有关的现金"],
  ["收回投资所收到的现金", "收回投资收到的现金"],
  ["取得投资收益所收到的现金", "取得投资收益收到的现金"],
  ["投资所支付的现金", "投资支付的现金"],
  ["借款所收到的现金", "取得借款收到的现金"],
  ["偿还债务所支付的现金", "偿还债务支付的现金"],
  [
    "分配股利、利润或偿还利息所支付的现金",
    "分配股利、利润或偿还利息支付的现金",
  ],
]);

export function cleanText(value) {
  return String(value ?? "")
    .replace(/\s+/g, "")
    .replace(/[：:]/g, "")
    .trim();
}

export function normalizeProject(value) {
  const withoutCode = cleanText(value).replace(/[（(]\d{2}[)）]$/, "");
  return PROJECT_ALIASES.get(withoutCode) ?? withoutCode;
}

export function normalizeVoucher(value) {
  const text = String(value ?? "")
    .trim()
    .replace(/[－—–]/g, "-")
    .replace(/\s+/g, "");
  return text.replace(/-0*(\d+)/g, "-$1");
}

function formatPeriod(year, month) {
  const numericYear = Number(year);
  const numericMonth = Number(month);
  if (
    !Number.isInteger(numericYear) ||
    numericYear < 1900 ||
    numericYear > 2999 ||
    !Number.isInteger(numericMonth) ||
    numericMonth < 1 ||
    numericMonth > 12
  ) {
    return "";
  }
  return `${numericYear}-${String(numericMonth).padStart(2, "0")}`;
}

export function normalizePeriod(value) {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) {
      return "";
    }
    return formatPeriod(value.getFullYear(), value.getMonth() + 1);
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    const compact = String(Math.trunc(value));
    if (/^\d{6}$/.test(compact)) {
      return formatPeriod(compact.slice(0, 4), compact.slice(4, 6));
    }
    if (value > 0) {
      const date = new Date(Date.UTC(1899, 11, 30) + Math.floor(value) * 86_400_000);
      return formatPeriod(date.getUTCFullYear(), date.getUTCMonth() + 1);
    }
    return "";
  }

  const source = String(value ?? "").trim();
  if (!source) {
    return "";
  }
  const compactMatch = source.match(/^(\d{4})(\d{2})$/);
  if (compactMatch) {
    return formatPeriod(compactMatch[1], compactMatch[2]);
  }
  const separatedMatch = source.match(/^(\d{4})\s*[-/.年]\s*(\d{1,2})(?:\s*[-/.月]|\s*月|$)/);
  return separatedMatch ? formatPeriod(separatedMatch[1], separatedMatch[2]) : "";
}

export function numberValue(value) {
  if (typeof value === "number") {
    return value;
  }
  const parsed = Number(String(value ?? "").replaceAll(",", "").trim());
  return Number.isFinite(parsed) ? parsed : 0;
}

export function addGroup(
  map,
  project,
  voucher,
  amount,
  originalVoucher,
  period = "",
) {
  const key = `${period}\u001f${project}\u001f${voucher}`;
  const current = map.get(key) ?? {
    key,
    period,
    project,
    voucher,
    originalVouchers: new Set(),
    count: 0,
    total: 0,
  };
  current.count += 1;
  current.total += amount;
  current.originalVouchers.add(String(originalVoucher ?? ""));
  map.set(key, current);
}

export function classify(detail, merged, tolerance = 0.005) {
  const amountDifference = (merged?.total ?? 0) - (detail?.total ?? 0);
  const roundedAbsoluteDifference =
    Math.round(Math.abs(amountDifference) * 1_000_000_000) / 1_000_000_000;
  const amountMatches = roundedAbsoluteDifference < tolerance;
  const countMatches = (merged?.count ?? 0) === (detail?.count ?? 0);
  let status = "核对一致";
  if (!detail) {
    status = "明细表无此凭证";
  } else if (!merged) {
    status = "整合表缺失";
  } else if (!amountMatches && !countMatches) {
    status = "金额及笔数不符";
  } else if (!amountMatches) {
    status = "金额不符";
  } else if (!countMatches) {
    status = "笔数不符";
  }
  return {
    status,
    period: detail?.period ?? merged?.period,
    project: detail?.project ?? merged?.project,
    voucher: detail?.voucher ?? merged?.voucher,
    detailOriginalVouchers: detail
      ? [...detail.originalVouchers].sort().join("、")
      : "",
    mergedOriginalVouchers: merged
      ? [...merged.originalVouchers].sort().join("、")
      : "",
    detailCount: detail?.count ?? 0,
    mergedCount: merged?.count ?? 0,
    detailTotal: detail?.total ?? 0,
    mergedTotal: merged?.total ?? 0,
    amountDifference,
  };
}

export function compareGroups(detailGroups, mergedGroups) {
  const allKeys = new Set([...detailGroups.keys(), ...mergedGroups.keys()]);
  const comparisons = new Map();
  const statusCounts = {};
  for (const key of allKeys) {
    const result = classify(detailGroups.get(key), mergedGroups.get(key));
    comparisons.set(key, result);
    statusCounts[result.status] = (statusCounts[result.status] ?? 0) + 1;
  }
  return { comparisons, statusCounts };
}
