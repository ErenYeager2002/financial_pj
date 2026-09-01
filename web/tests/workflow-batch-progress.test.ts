import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import type { WorkflowRead } from '../src/features/platform-api/types.ts';
import {
  batchFailureGuidance,
  batchFetchedDataWorkflow,
  currentWorkflowForBatch,
  isWaitingWorkflow,
  preferredWorkflow,
  preferredWorkflowForBatch,
  workflowAttentionHint,
  workflowStatusInBatch,
  workflowStatusLabel
} from '../src/features/workflow-agent/workflow-batch-selection.ts';

function workflow(overrides: Partial<WorkflowRead> = {}): WorkflowRead {
  return {
    actions: [],
    artifacts: [],
    batch_sequence: 1,
    created_at: '2026-08-21T00:00:00Z',
    current_step: '',
    current_step_label: '',
    display_id: 'ar-hexiao-daily_8.21_1',
    error_message: '',
    fetched_data_available: false,
    fetched_data_review_status: '',
    files: {},
    id: 'workflow-1',
    material_source_workflow_id: '',
    messages: [],
    model_name: '',
    model_provider: '',
    owner_id: 'owner-1',
    progress: 0,
    progress_message: '',
    reconciliation_date: '2026-08-21',
    requires_confirmation: true,
    skill_id: 'ar-hexiao-daily',
    skill_name: '应收核销日清',
    skill_version: '1.6.3',
    stage: 'queued',
    state: 'queued',
    step_error: '',
    updated_at: '2026-08-21T00:00:00Z',
    ...overrides
  };
}

test('批次日期默认选择按待确认、处理中、失败、未完成的顺序', () => {
  const waitingConfirmation = workflow({
    id: 'workflow-confirm',
    batch_sequence: 3,
    stage: 'awaiting_apply_confirmation',
    state: 'waiting_confirmation'
  });
  const running = workflow({ id: 'workflow-running', batch_sequence: 2, state: 'running' });
  const failed = workflow({
    id: 'workflow-failed',
    batch_sequence: 1,
    stage: 'failed',
    state: 'failed'
  });

  assert.equal(preferredWorkflow([running, failed, waitingConfirmation])?.id, 'workflow-confirm');
  assert.equal(preferredWorkflow([running, failed])?.id, 'workflow-running');
  assert.equal(
    preferredWorkflow([failed, workflow({ id: 'workflow-queued' })])?.id,
    'workflow-failed'
  );
});

test('全部结束后批次日期默认选择最后一天', () => {
  const first = workflow({ id: 'workflow-1', state: 'succeeded', stage: 'completed' });
  const last = workflow({
    id: 'workflow-2',
    batch_sequence: 2,
    reconciliation_date: '2026-08-22',
    state: 'succeeded',
    stage: 'completed'
  });

  assert.equal(preferredWorkflow([first, last])?.id, 'workflow-2');
});

test('终态批次不返回当前执行日期，失败批次默认定位失败日期', () => {
  const staleRunning = workflow({ id: 'stale-running', state: 'running', batch_sequence: 1 });
  const failed = workflow({
    id: 'failed-date',
    state: 'failed',
    stage: 'failed',
    batch_sequence: 2
  });

  for (const state of ['failed', 'cancelled', 'succeeded']) {
    assert.equal(currentWorkflowForBatch({ state, workflows: [staleRunning, failed] }), null);
  }
  assert.equal(
    preferredWorkflowForBatch({ state: 'failed', workflows: [staleRunning, failed] })?.id,
    'failed-date'
  );
});

test('终态批次覆盖陈旧子状态，后续日期不显示处理中', () => {
  const succeeded = workflow({ state: 'succeeded', stage: 'completed', batch_sequence: 1 });
  const failed = workflow({ state: 'failed', stage: 'failed', batch_sequence: 2 });
  const staleRunning = workflow({ state: 'running', stage: 'preparing', batch_sequence: 3 });
  const workflows = [succeeded, failed, staleRunning];

  assert.equal(workflowStatusInBatch('failed', workflows, succeeded), '已完成');
  assert.equal(workflowStatusInBatch('failed', workflows, failed), '失败');
  assert.equal(workflowStatusInBatch('failed', workflows, staleRunning), '未开始');
  assert.equal(workflowStatusInBatch('cancelled', workflows, staleRunning), '已取消');
  assert.equal(workflowStatusInBatch('succeeded', workflows, staleRunning), '已完成');
});

test('失败日期不显示原始异常、路径、地址或凭据', () => {
  for (const message of [
    'Traceback: /srv/app/task.py line 12',
    'request failed https://internal.example/token',
    'token=super-secret',
    'password=hunter2',
    '普通数据库异常详情'
  ]) {
    assert.equal(
      workflowAttentionHint(workflow({ state: 'failed', stage: 'failed', step_error: message })),
      '该日期未完成，请查看失败步骤'
    );
  }
});

test('失败指引区分可重试和不可重试并说明后续日期', () => {
  const failed = workflow({
    state: 'failed',
    stage: 'failed',
    batch_sequence: 2,
    reconciliation_date: '2026-08-22',
    current_step_label: '核销校验'
  });
  const later = workflow({ state: 'queued', batch_sequence: 3, reconciliation_date: '2026-08-23' });
  const retryable = batchFailureGuidance({
    state: 'failed',
    retryable: true,
    can_retry: true,
    retry_message: '可从失败日期继续。',
    retry_block_reason: '',
    workflows: [workflow({ state: 'succeeded', stage: 'completed' }), failed, later]
  });
  assert.equal(retryable?.failedDate, '2026-08-22');
  assert.equal(retryable?.failedStep, '核销校验');
  assert.match(retryable?.laterDatesMessage ?? '', /1 个后续日期.*尚未开始/);
  assert.match(retryable?.nextAction ?? '', /已成功日期不会重复执行/);
  assert.doesNotMatch(retryable?.nextAction ?? '', /联系管理员/);

  const blocked = batchFailureGuidance({
    state: 'failed',
    retryable: false,
    can_retry: false,
    retry_message: '失败发生在写入阶段，不能自动重试；请联系财务管理员。',
    retry_block_reason: '失败发生在写入阶段，不能自动重试；请联系财务管理员。',
    workflows: [failed, later]
  });
  assert.match(blocked?.nextAction ?? '', /写入阶段/);
  assert.match(blocked?.nextAction ?? '', /财务管理员/);

  const unauthorized = batchFailureGuidance({
    state: 'failed',
    retryable: true,
    can_retry: false,
    retry_message: '可从失败日期继续。',
    retry_block_reason: '当前账号没有执行权限，请联系平台管理员。',
    workflows: [failed, later]
  });
  assert.match(unauthorized?.nextAction ?? '', /没有执行权限/);
  assert.doesNotMatch(unauthorized?.nextAction ?? '', /已成功日期不会重复执行/);
});

test('日期任务状态使用中文并区分等待任务', () => {
  assert.equal(workflowStatusLabel(workflow({ state: 'queued', stage: 'queued' })), '等待');
  assert.equal(workflowStatusLabel(workflow({ state: 'running', stage: 'preparing' })), '处理中');
  assert.equal(
    workflowStatusLabel(
      workflow({ state: 'waiting_confirmation', stage: 'awaiting_fetched_data_confirmation' })
    ),
    '待检查取数'
  );
  assert.equal(workflowStatusLabel(workflow({ state: 'failed', stage: 'failed' })), '失败');
  assert.equal(isWaitingWorkflow(workflow({ state: 'queued', stage: 'queued' })), true);
});

test('批次取数复核使用重试日期的待检查状态而不是第一天状态', () => {
  const first = workflow({ state: 'succeeded', stage: 'completed' });
  const retried = workflow({
    id: 'workflow-retried',
    batch_sequence: 19,
    reconciliation_date: '2026-08-19',
    fetched_data_available: true,
    fetched_data_review_status: 'waiting',
    stage: 'awaiting_fetched_data_confirmation',
    state: 'waiting_confirmation'
  });

  assert.equal(batchFetchedDataWorkflow([first, retried])?.id, 'workflow-retried');
});

test('批次详情页只渲染一张日期流程图并保留手动选择状态', () => {
  const progress = readFileSync(
    new URL(
      '../src/features/workflow-agent/components/workflow-batch-progress.tsx',
      import.meta.url
    ),
    'utf8'
  );

  assert.equal((progress.match(/<WorkflowProgressCard\b/g) ?? []).length, 1);
  assert.match(progress, /selectedWorkflowId/);
  assert.match(progress, /manualSelection/);
  assert.match(progress, /返回当前任务/);
  assert.match(progress, /重试失败日期/);
  assert.match(progress, /\{batch\.can_retry &&/);
  assert.doesNotMatch(progress, /\{batch\.retryable &&/);
  assert.match(progress, /正在重新执行/);
  assert.match(
    progress,
    /<PaginatedCollection ariaLabel='\u6279\u6b21\u65e5\u671f\u4efb\u52a1\u5217\u8868'/
  );
  assert.doesNotMatch(progress, /workflows\.length > 5|h-\[25rem\]/);
  assert.match(progress, /bg-amber-600/);
  assert.match(progress, /批次产出/);
  assert.doesNotMatch(progress, /打开任务详情/);
  assert.doesNotMatch(progress, /当前任务操作/);
});

test('批次详情页展示整合核销日清和最终工作副本', () => {
  const progress = readFileSync(
    new URL(
      '../src/features/workflow-agent/components/workflow-batch-progress.tsx',
      import.meta.url
    ),
    'utf8'
  );

  assert.match(progress, /function batchOutputFiles/);
  assert.match(progress, /function BatchOutputCard/);
  assert.match(progress, /<CardTitle className='text-base'>批次产出<\/CardTitle>/);
  assert.match(progress, /api\/platform\/files/);
  assert.match(progress, /整合核销日清/);
  assert.doesNotMatch(progress, /包含核销日/);
  assert.match(progress, /仅处理已选/);
  assert.match(progress, /盈亏核算表/);
  assert.match(progress, /到账流转表/);
  assert.doesNotMatch(progress, /所有日期的结果文件集中显示/);
});

test('批次子任务提供所属批次返回入口，独立任务仍返回任务列表', () => {
  const panel = readFileSync(
    new URL('../src/features/workflow-agent/components/workflow-agent-panel.tsx', import.meta.url),
    'utf8'
  );

  assert.match(panel, /返回所属批次/);
  assert.match(panel, /workflow\.batch_id/);
  assert.match(panel, /返回任务列表/);
});

test('批次子任务详情路径回到批次详情，独立任务详情仍保留', () => {
  const page = readFileSync(
    new URL('../src/app/dashboard/workflows/[workflowId]/page.tsx', import.meta.url),
    'utf8'
  );

  assert.match(page, /if \(workflow\.batch_id\)/);
  assert.match(page, /dashboard\/workflows\/batches/);
  assert.match(page, /redirect\(/);
});

test('失败日期重试走同源代理并校验批次标识', () => {
  const route = readFileSync(
    new URL('../src/app/api/platform/workflow-batches/[batchId]/retry/route.ts', import.meta.url),
    'utf8'
  );
  assert.match(route, /export async function POST/);
  assert.match(route, /workflow-batches\/\$\{batchId\}\/retry/);
  assert.match(route, /const BATCH_ID/);
});
