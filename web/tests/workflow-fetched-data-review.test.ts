import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  buildFetchedDataPreviewRequest,
  lastPageOffset,
  parseSupplementIdentifiers,
  partitionFetchedArGroups
} from '../src/features/workflow-agent/workflow-fetched-data-input.ts';

const dialog = readFileSync(
  new URL(
    '../src/features/workflow-agent/components/workflow-fetched-data-dialog.tsx',
    import.meta.url
  ),
  'utf8'
);
const batchProgress = readFileSync(
  new URL('../src/features/workflow-agent/components/workflow-batch-progress.tsx', import.meta.url),
  'utf8'
);
const flow = readFileSync(
  new URL('../src/features/workflow-agent/workflow-flow.ts', import.meta.url),
  'utf8'
);

test('取数后必须提供人工确认和按 AR/SO 编号补取入口', () => {
  assert.match(dialog, /数据完整，继续处理/);
  assert.match(dialog, /发现缺失数据/);
  assert.match(dialog, /缺失 AR 编号/);
  assert.match(dialog, /缺失 SO 编号/);
  assert.match(dialog, /按编号补取/);
  assert.match(dialog, /fetched-data\/\$\{action\}/);
});

test('已完成任务仍提供直接查看已保存取数数据的入口', () => {
  const panel = readFileSync(
    new URL('../src/features/workflow-agent/components/workflow-agent-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(panel, /workflow\.fetched_data_available && isTerminal\(workflow\)/);
  assert.match(panel, /查看已保存的取数数据/);
});

test('人工确认操作区固定在数据滚动区之外', () => {
  assert.match(dialog, /data-testid='fetched-data-scroll-region'/);
  assert.match(dialog, /data-testid='fetched-data-review-actions'/);
  assert.match(dialog, /fetched-data-review-actions'[\s\S]*shrink-0[\s\S]*border-t/);
  assert.match(dialog, /max-h-\[42dvh\][\s\S]*overflow-y-auto/);
});

test('流程卡在智云取数后显示人工检查节点', () => {
  assert.match(flow, /review_fetched_data.*检查取数数据/);
  assert.match(flow, /awaiting_fetched_data_confirmation/);
});

test('多日批次只提供一个审核入口并按日期查看', () => {
  assert.match(batchProgress, /WorkflowFetchedDataDialog/);
  assert.match(batchProgress, /本批次智云取数/);
  assert.match(dialog, /workflow-batches/);
  assert.match(dialog, /reconciliation_date/);
  assert.match(dialog, /batch\.reconciliation_dates\.map/);
});

test('AR/SO 编号在前端规范化、去重并拦截错误前缀', () => {
  assert.deepEqual(parseSupplementIdentifiers(' ar26070140，AR26070140\nAR_A-12 ', 'AR'), {
    values: ['AR26070140', 'AR_A-12'],
    invalid: []
  });
  assert.deepEqual(parseSupplementIdentifiers('SO26020320; AR26070140', 'SO'), {
    values: ['SO26020320'],
    invalid: ['AR26070140']
  });
});

test('分页末页从完整页边界开始且不与上一页重叠', () => {
  assert.equal(lastPageOffset(0, 50), 0);
  assert.equal(lastPageOffset(50, 50), 0);
  assert.equal(lastPageOffset(51, 50), 50);
  assert.equal(lastPageOffset(101, 50), 100);
});

test('取数复核提供按日期的业务摘要、合法空结果和可读补取记录', () => {
  assert.match(dialog, /本日 AR 汇总金额/);
  assert.match(dialog, /本日总核销金额/);
  assert.match(dialog, /AR 覆盖/);
  assert.match(dialog, /AR\/SO 覆盖/);
  assert.match(dialog, /未提供/);
  assert.match(dialog, /当天没有核销记录，可以继续/);
  assert.match(dialog, /本日没有核销记录/);
  assert.match(dialog, /标记本日已完成并跳过/);
  assert.match(dialog, /补取记录/);
  assert.doesNotMatch(dialog, /JSON\.stringify\(supplementHistory/);
});

test('取数复核使用一张按 AR、SO、SOD 逐级展开的业务关系表', () => {
  assert.match(dialog, /按 AR 分组/);
  assert.match(dialog, /preview\.ar_groups/);
  assert.match(dialog, /expandedArIds/);
  assert.match(dialog, /expandedSoIds/);
  assert.match(dialog, /aria-expanded/);
  assert.match(dialog, /AR 编号/);
  assert.match(dialog, /到账日期/);
  assert.match(dialog, /SO 编号/);
  assert.match(dialog, /交付日期/);
  assert.match(dialog, /核销记录/);
  assert.match(dialog, /核销日期/);
  assert.match(dialog, /SOD 编号/);
  assert.match(dialog, /项目状态/);
  assert.match(dialog, /payment\.amount_original/);
  assert.doesNotMatch(dialog, /lg:grid-cols-2/);
  assert.doesNotMatch(dialog, />业务日期</);
  assert.doesNotMatch(dialog, />客户\/订单</);
  assert.doesNotMatch(dialog, /recordValue/);
  assert.doesNotMatch(dialog, /<Tabs/);
});

test('AR 分组表在自己的滚动区域内保持表头可见', () => {
  assert.match(dialog, /data-testid='ar-group-table-scroll'/);
  assert.match(dialog, /overflow-auto/);
  assert.match(dialog, /table-container.*overflow-visible/);
  assert.match(dialog, /sticky top-0 z-20/);
});

test('批次状态轮询不会重新触发取数预览请求', () => {
  const polledBatchSnapshots = [
    '2026-08-25T09:10:00Z',
    '2026-08-25T09:10:05Z',
    '2026-08-25T09:10:10Z'
  ];
  const requests = polledBatchSnapshots.map((_updatedAt) =>
    buildFetchedDataPreviewRequest({
      isBatch: true,
      resourceId: 'batch-1',
      reconciliationDate: '2026-08-24',
      offset: 0,
      pageSize: 50,
      query: '',
      issuesOnly: false,
      supplementRevision: 0
    })
  );

  assert.equal(new Set(requests.map((request) => request.key)).size, 1);
  assert.equal(
    buildFetchedDataPreviewRequest({
      isBatch: true,
      resourceId: 'batch-1',
      reconciliationDate: '2026-08-24',
      offset: 0,
      pageSize: 50,
      query: '',
      issuesOnly: false,
      supplementRevision: 1
    }).key === requests[0].key,
    false
  );
  assert.doesNotMatch(dialog, /resourceUpdatedAt/);
  assert.match(dialog, /\[open, previewRequest\]/);
});

test('本日 AR 与仅用于累计核对的历史父回款分组显示', () => {
  const groups = [
    {
      ar_id: 'AR26080063',
      payments: [{ historical_parent_only: false }]
    },
    {
      ar_id: 'AR25110238',
      payments: [{ historical_parent_only: true }]
    },
    {
      ar_id: 'AR-MIXED',
      payments: [{ historical_parent_only: true }, { historical_parent_only: false }]
    }
  ];

  assert.deepEqual(partitionFetchedArGroups(groups), {
    current: [groups[0], groups[2]],
    historicalReferences: [groups[1]]
  });
  assert.match(dialog, /历史累计参考/);
  assert.match(dialog, /不属于本日处理对象/);
  assert.match(dialog, /当前页：本日 .* 个 AR/);
});
