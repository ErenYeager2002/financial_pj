import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

import {
  arTaskBusinessId,
  arTaskDateLabel,
  arTaskFailureSummary,
  arTaskStatus,
  arTaskUpdatedLabel,
  buildArTaskListRows,
  type ArTaskListSource
} from '../src/features/workflow-agent/ar-task-list-presentation.ts';

test('批次显示日期范围和日期数，单日任务只显示业务日期', () => {
  assert.equal(
    arTaskDateLabel({ reconciliation_dates: ['2026-08-24', '2026-08-21', '2026-08-22'] }),
    '2026-08-21 至 2026-08-24 · 共 3 天'
  );
  assert.equal(arTaskDateLabel({ reconciliation_date: '2026-08-21' }), '2026-08-21');
});

test('应收核销内部状态统一显示中文', () => {
  assert.deepEqual(
    ['queued', 'running', 'waiting_confirmation', 'failed', 'succeeded', 'cancelled'].map(
      (state) => arTaskStatus({ state, stage: state }).label
    ),
    ['等待处理', '处理中', '待确认', '失败', '已完成', '已取消']
  );
  assert.deepEqual(
    ['active', 'finalizing', 'cancelling', 'unexpected'].map(
      (state) => arTaskStatus({ state }).label
    ),
    ['待处理', '处理中', '取消中', '状态未知']
  );
});

test('失败摘要隐藏技术信息并限制长度，非失败项不返回摘要', () => {
  assert.equal(
    arTaskFailureSummary({
      state: 'failed',
      error_message: '读取 C:\\finance\\secret.xlsx 失败，请访问 https://internal.example/task'
    }),
    '任务未完成，请进入详情查看失败步骤。'
  );
  assert.equal(
    arTaskFailureSummary({ state: 'failed', error_message: `核销校验失败：${'明细'.repeat(100)}` })
      .length,
    120
  );
  assert.equal(arTaskFailureSummary({ state: 'running', error_message: '不应显示' }), '');
});

test('更新时间转换为上海时区的稳定格式', () => {
  assert.equal(arTaskUpdatedLabel('2026-08-21T00:30:00Z'), '2026-08-21 08:30');
});

test('业务任务号作为次要信息且不会退回显示 UUID', () => {
  assert.equal(arTaskBusinessId('AR-20260821-0001', 'uuid'), 'AR-20260821-0001');
  assert.equal(
    arTaskBusinessId(
      '123e4567-e89b-42d3-a456-426614174000',
      '123e4567-e89b-42d3-a456-426614174000'
    ),
    ''
  );
});

test('列表视图模型正确接线批次、单日、失败和非失败数据', () => {
  const base: ArTaskListSource = {
    id: '123e4567-e89b-42d3-a456-426614174000',
    display_id: 'AR-20260821-0001',
    skill_name: '应收核销日清',
    state: 'failed',
    progress: 35,
    progress_message: '核销校验失败',
    error_message: '校验结果不一致',
    updated_at: '2026-08-21T00:30:00Z'
  };
  const rows = buildArTaskListRows(
    [{ ...base, reconciliation_dates: ['2026-08-21', '2026-08-22'] }],
    [
      {
        ...base,
        id: '223e4567-e89b-42d3-a456-426614174000',
        display_id: '223e4567-e89b-42d3-a456-426614174000',
        state: 'running',
        error_message: '不应显示',
        reconciliation_date: '2026-08-20'
      },
      { ...base, id: 'batch-child', batch_id: 'batch-1', reconciliation_date: '2026-08-21' }
    ]
  );

  assert.equal(rows.length, 2);
  assert.deepEqual(
    rows.map((row) => ({
      kind: row.kindLabel,
      date: row.dateLabel,
      status: row.status.label,
      progress: row.progress,
      message: row.progressMessage,
      updated: row.updatedLabel,
      id: row.displayId,
      failure: row.failureSummary
    })),
    [
      {
        kind: '批次',
        date: '2026-08-21 至 2026-08-22 · 共 2 天',
        status: '失败',
        progress: 35,
        message: '核销校验失败',
        updated: '2026-08-21 08:30',
        id: 'AR-20260821-0001',
        failure: '校验结果不一致'
      },
      {
        kind: '单日',
        date: '2026-08-20',
        status: '处理中',
        progress: 35,
        message: '核销校验失败',
        updated: '2026-08-21 08:30',
        id: '',
        failure: ''
      }
    ]
  );

  const component = fs.readFileSync(
    path.join(process.cwd(), 'src/features/workflow-agent/components/ar-task-list.tsx'),
    'utf8'
  );
  assert.match(component, /buildArTaskListRows\(batches, workflows\)/);
  assert.doesNotMatch(component, /\{task\.id\}/);
});
