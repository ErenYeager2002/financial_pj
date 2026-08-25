import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  addWorkflowDate,
  workflowInitialDateSelection,
  workflowInitialDateSelectionKey,
  workflowDateRangeSelection,
  workflowDateRangeSummary,
  toggleWorkflowDate,
  validateWorkflowDateRange,
  workflowDateKey
} from '../src/features/workflow-agent/workflow-date-selection.ts';

test('提醒日期初始化重复执行时不会清空已经带入的日期', () => {
  const maximum = new Date(2026, 7, 25);
  const initialDates = ['2026-08-21', '2026-08-22', '2026-08-24'];
  const selectionKey = workflowInitialDateSelectionKey('ar-hexiao-daily', initialDates);
  let selectedDates: Date[] = [];
  const first = workflowInitialDateSelection(
    initialDates,
    'ar-hexiao-daily',
    'ar-hexiao-daily',
    maximum,
    ''
  );
  if (first !== null) selectedDates = first;
  const second = workflowInitialDateSelection(
    initialDates,
    'ar-hexiao-daily',
    'ar-hexiao-daily',
    maximum,
    selectionKey
  );
  if (second !== null) selectedDates = second;

  assert.deepEqual(selectedDates.map(workflowDateKey), initialDates);
});

test('任务页面复用后收到新的提醒日期时会重新选择日期', () => {
  const maximum = new Date(2026, 7, 25);
  const previousSelectionKey = workflowInitialDateSelectionKey('ar-hexiao-daily', []);
  const initialDates = ['2026-08-16', '2026-08-17', '2026-08-21'];
  const selectedDates = workflowInitialDateSelection(
    initialDates,
    'ar-hexiao-daily',
    'ar-hexiao-daily',
    maximum,
    previousSelectionKey
  );

  assert.notEqual(selectedDates, null);
  assert.deepEqual((selectedDates ?? []).map(workflowDateKey), initialDates);
});

const maximum = new Date(2026, 7, 20);
const launcher = readFileSync(
  new URL('../src/features/workflow-agent/components/workflow-launcher.tsx', import.meta.url),
  'utf8'
);

test('drag selection adds every entered date once', () => {
  let selected: Date[] = [];
  selected = addWorkflowDate(selected, new Date(2026, 7, 18), maximum);
  selected = addWorkflowDate(selected, new Date(2026, 7, 19), maximum);
  selected = addWorkflowDate(selected, new Date(2026, 7, 18), maximum);
  assert.deepEqual(selected.map(workflowDateKey), ['2026-08-18', '2026-08-19']);
});

test('single click toggles one date after drag selection', () => {
  const selected = [new Date(2026, 7, 18), new Date(2026, 7, 19)];
  assert.deepEqual(
    toggleWorkflowDate(selected, new Date(2026, 7, 18), maximum).map(workflowDateKey),
    ['2026-08-19']
  );
});

test('future dates cannot be selected by click or drag', () => {
  const future = new Date(2026, 7, 21);
  assert.deepEqual(addWorkflowDate([], future, maximum), []);
  assert.deepEqual(toggleWorkflowDate([], future, maximum), []);
});

test('multi-date tasks require every consecutive calendar day', () => {
  assert.equal(
    validateWorkflowDateRange([
      new Date(2026, 7, 17),
      new Date(2026, 7, 18),
      new Date(2026, 7, 19)
    ]),
    ''
  );
  assert.match(
    validateWorkflowDateRange([new Date(2026, 7, 17), new Date(2026, 7, 19)]),
    /连续日期/
  );
  assert.equal(
    validateWorkflowDateRange([
      new Date(2026, 7, 21),
      new Date(2026, 7, 22),
      new Date(2026, 7, 23),
      new Date(2026, 7, 24)
    ]),
    ''
  );
});

test('selected dates have an explicit high-contrast visual state', () => {
  assert.match(launcher, /data-workflow-selected=/);
  assert.match(launcher, /data-\[workflow-selected=true\]:bg-primary/);
  assert.match(launcher, /data-\[workflow-selected=true\]:text-primary-foreground/);
});

test('all selected dates can be cleared with one button', () => {
  assert.match(launcher, /清除全部日期/);
  assert.match(launcher, /setSelectedDates\(\[\]\)/);
});

test('date inputs include every calendar day, including weekends', () => {
  const selection = workflowDateRangeSelection('2026-08-11', '2026-08-20', new Date(2026, 7, 20));
  assert.equal(selection.error, '');
  assert.deepEqual(selection.dates.map(workflowDateKey), [
    '2026-08-11',
    '2026-08-12',
    '2026-08-13',
    '2026-08-14',
    '2026-08-15',
    '2026-08-16',
    '2026-08-17',
    '2026-08-18',
    '2026-08-19',
    '2026-08-20'
  ]);
});

test('date inputs reject reversed and future ranges', () => {
  assert.match(
    workflowDateRangeSelection('2026-08-20', '2026-08-11', new Date(2026, 7, 20)).error,
    /开始日期不能晚于结束日期/
  );
  assert.match(
    workflowDateRangeSelection('2026-08-19', '2026-08-21', new Date(2026, 7, 20)).error,
    /不能晚于今天/
  );
});

test('date range summary counts weekend reconciliation dates', () => {
  const summary = workflowDateRangeSummary([
    new Date(2026, 7, 11),
    new Date(2026, 7, 12),
    new Date(2026, 7, 13),
    new Date(2026, 7, 14),
    new Date(2026, 7, 15),
    new Date(2026, 7, 16),
    new Date(2026, 7, 17),
    new Date(2026, 7, 18),
    new Date(2026, 7, 19),
    new Date(2026, 7, 20)
  ]);
  assert.deepEqual(summary, { dateCount: 10 });
});
