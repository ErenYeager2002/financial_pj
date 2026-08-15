import test from "node:test";
import assert from "node:assert/strict";

import {
  addGroup,
  classify,
  compareGroups,
  normalizeProject,
  normalizeVoucher,
} from "../scripts/reconciliation_core.mjs";

function group(project, voucher, count, total) {
  return {
    project,
    voucher,
    count,
    total,
    originalVouchers: new Set([voucher]),
  };
}

test("凭证号去除数字前导零并统一连字符", () => {
  assert.equal(normalizeVoucher(" 记－0032 "), "记-32");
  assert.equal(normalizeVoucher("记-32"), "记-32");
  assert.equal(normalizeVoucher("记-0007"), "记-7");
});

test("现金流量项目去除行次并应用明确别名", () => {
  assert.equal(
    normalizeProject(" 收到的其他与经营活动的现金(03) "),
    "收到其他与经营活动有关的现金",
  );
  assert.equal(
    normalizeProject("借款所收到的现金（18）"),
    "取得借款收到的现金",
  );
});

test("用户示例的八笔同金额判定一致", () => {
  const detail = group("销售商品、提供劳务收到的现金", "记-32", 8, 1005354);
  const merged = group("销售商品、提供劳务收到的现金", "记-32", 8, 1005354);
  assert.equal(classify(detail, merged).status, "核对一致");
});

test("金额、笔数和缺失状态分别分类", () => {
  const base = group("项目", "记-3", 1, 100);
  assert.equal(
    classify(base, group("项目", "记-3", 1, 101)).status,
    "金额不符",
  );
  assert.equal(
    classify(base, group("项目", "记-3", 2, 100)).status,
    "笔数不符",
  );
  assert.equal(
    classify(base, group("项目", "记-3", 2, 101)).status,
    "金额及笔数不符",
  );
  assert.equal(classify(base, undefined).status, "整合表缺失");
  assert.equal(classify(undefined, base).status, "明细表无此凭证");
});

test("金额误差小于半分时视为一致", () => {
  const base = group("项目", "记-3", 1, 100);
  assert.equal(
    classify(base, group("项目", "记-3", 1, 100.004)).status,
    "核对一致",
  );
  assert.equal(
    classify(base, group("项目", "记-3", 1, 100.005)).status,
    "金额不符",
  );
});

test("分组必须同时包含项目和规范凭证号", () => {
  const groups = new Map();
  addGroup(groups, "项目甲", "记-3", 10, "记-0003");
  addGroup(groups, "项目乙", "记-3", 20, "记-3");
  assert.equal(groups.size, 2);
  const { statusCounts } = compareGroups(groups, new Map(groups));
  assert.deepEqual(statusCounts, { 核对一致: 2 });
});

test("凭证号为空的基准记录仍保留为待核对组", () => {
  const groups = new Map();
  addGroup(groups, "项目甲", "", 100, "");
  const item = groups.get("项目甲\u001f");
  assert.equal(groups.size, 1);
  assert.equal(item.count, 1);
  assert.equal(item.total, 100);
});
