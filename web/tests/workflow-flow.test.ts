import assert from 'node:assert/strict';
import test from 'node:test';
import { workflowError, workflowFlow } from '../src/features/workflow-agent/workflow-flow.ts';

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

test('完成任务的流程卡片全部完成', () => {
  assert.ok(
    workflowFlow({ state: 'succeeded', stage: 'completed', progress: 100 }).every(
      (node) => node.state === 'complete'
    )
  );
});
