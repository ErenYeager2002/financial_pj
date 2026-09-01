import assert from 'node:assert/strict';
import test from 'node:test';
import {
  workflowError,
  workflowFlow,
  workflowSummaryFlow
} from '../src/features/workflow-agent/workflow-flow.ts';

test('后台任务流程卡片把当前步骤标为进行中', () => {
  const nodes = workflowFlow({
    state: 'running',
    stage: 'preparing',
    progress: 53,
    current_step: 'classify_receipts'
  });

  assert.equal(nodes.find((node) => node.key === 'fetch_zhiyun')?.state, 'complete');
  assert.equal(nodes.find((node) => node.key === 'classify_receipts')?.state, 'active');
  assert.equal(nodes.find((node) => node.key === 'validate_plan')?.state, 'pending');
});

test('后台任务流程卡片把失败定位到当前步骤并展示错误', () => {
  const input = {
    state: 'failed',
    stage: 'failed',
    progress: 53,
    current_step: 'classify_receipts',
    current_step_label: '正在按核销日期判定回款和订单',
    step_error: '智云返回字段缺失'
  };

  assert.equal(
    workflowFlow(input).find((node) => node.key === 'classify_receipts')?.state,
    'error'
  );
  assert.deepEqual(workflowError(input), {
    step: '正在按核销日期判定回款和订单',
    message: '智云返回字段缺失'
  });
});

test('拆分后的取数与写入动作仍定位到原有员工流程步骤', () => {
  const fetch = workflowFlow({
    state: 'failed',
    stage: 'failed',
    progress: 15,
    actions: [{ name: 'build_fetch_preview', state: 'failed', error_message: '预览失败' }]
  });
  const write = workflowFlow({
    state: 'failed',
    stage: 'failed',
    progress: 85,
    actions: [{ name: 'apply_material_update', state: 'failed', error_message: '写入失败' }]
  });

  assert.equal(fetch.find((node) => node.key === 'fetch_zhiyun')?.state, 'error');
  assert.equal(write.find((node) => node.key === 'write_files')?.state, 'error');
});

test('完成任务的流程卡片全部完成', () => {
  assert.ok(
    workflowFlow({ state: 'succeeded', stage: 'completed', progress: 100 }).every(
      (node) => node.state === 'complete'
    )
  );
});

test('流程默认按五组展示，细分步骤仍保留', () => {
  const groups = workflowSummaryFlow({
    state: 'running',
    stage: 'preparing',
    progress: 35,
    current_step: 'classify_receipts'
  });
  assert.deepEqual(
    groups.map((group) => group.label),
    ['准备材料', '智云取数', '数据检查', '核销处理', '完成']
  );
  assert.equal(groups.find((group) => group.key === 'checks')?.state, 'active');
  assert.equal(groups.find((group) => group.key === 'fetch')?.state, 'complete');
});
