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

const executionPhases = [
  ['inspect_materials', 24, 'checks'],
  ['classify_receipts', 32, 'checks'],
  ['review_order_evidence', 40, 'checks'],
  ['validate_reconciliation', 48, 'checks'],
  ['build_initial_report', 54, 'processing'],
  ['stage_reconciliation', 58, 'processing'],
  ['write_ledger', 66, 'processing'],
  ['write_receipt_flow', 72, 'processing'],
  ['verify_reconciliation', 80, 'processing'],
  ['rescan_holds', 86, 'processing'],
  ['build_final_report', 92, 'processing'],
  ['review_final_report', 95, 'processing'],
  ['publish_reconciliation', 97, 'completed'],
  ['complete_reconciliation', 99, 'completed']
] as const;

test('新版核销连续阶段在详细流程和五组流程中不会回到第一步', () => {
  let previousIndex = -1;
  let previousGroupIndex = -1;
  for (const [phaseIndex, [phase, progress, group]] of executionPhases.entries()) {
    const input = {
      state: 'running',
      stage: progress < 58 ? 'preparing' : 'applying',
      progress,
      current_step: phase,
      actions: executionPhases.slice(0, phaseIndex + 1).map(([name], index) => ({
        name: `ar_${name}`,
        state: index === phaseIndex ? 'running' : 'succeeded',
        error_message: ''
      }))
    };
    const nodes = workflowFlow(input);
    const groups = workflowSummaryFlow(input);
    const activeIndex = nodes.findIndex((node) => node.state === 'active');
    const activeGroupIndex = groups.findIndex((node) => node.state === 'active');
    assert.equal(nodes[activeIndex]?.key, phase);
    assert.equal(groups[activeGroupIndex]?.key, group);
    assert.ok(activeIndex > previousIndex);
    assert.ok(activeGroupIndex >= previousGroupIndex);
    assert.equal(nodes.find((node) => node.key === 'queued')?.state, 'complete');
    assert.equal(nodes.at(-1)?.state, 'pending');
    previousIndex = activeIndex;
    previousGroupIndex = activeGroupIndex;
  }
});

test('新版核销缺少当前步骤时用失败动作定位，不回到提交任务', () => {
  for (const [phase, progress] of executionPhases) {
    const input = {
      state: 'failed', stage: 'failed', progress,
      actions: [{ name: `ar_${phase}`, state: 'failed', error_message: '阶段失败' }],
      step_error: '阶段失败'
    };
    const failed = workflowFlow(input).find((node) => node.state === 'error');
    assert.equal(failed?.key, phase);
    assert.equal(workflowError(input)?.step, failed?.label);
  }
});

test('新版流程在初始化、范围报告和任务完成时保留正确位置', () => {
  const input = {
    state: 'running', stage: 'preparing', progress: 20,
    current_step: 'inspect_inputs',
    actions: [{ name: 'ar_inspect_materials', state: 'queued', error_message: '' }]
  };
  assert.equal(workflowFlow(input).find((node) => node.state === 'active')?.key, 'inspect_materials');
  assert.equal(workflowFlow({ ...input, stage: 'finalizing', current_step: 'finalize_batch' })
    .find((node) => node.state === 'active')?.key, 'finalize_batch');
  // Completion can retain the last execution step in the backend context.
  const completed = { ...input, state: 'succeeded', stage: 'completed', progress: 100,
    current_step: 'complete_reconciliation' };
  assert.ok(workflowFlow(completed).every((node) => node.state === 'complete'));
  assert.ok(workflowSummaryFlow(completed).every((node) => node.state === 'complete'));
});

test('取消后的新版核销保留最后执行步骤', () => {
  const nodes = workflowFlow({
    state: 'cancelled', stage: 'cancelled', progress: 80,
    current_step: 'verify_reconciliation'
  });
  assert.equal(nodes.find((node) => node.key === 'queued')?.state, 'complete');
  assert.equal(nodes.find((node) => node.key === 'verify_reconciliation')?.state, 'active');
  assert.equal(nodes.find((node) => node.key === 'rescan_holds')?.state, 'pending');
});

test('新版动作名称可直接定位阶段，排队等待也保留执行位置', () => {
  for (const [phase, progress] of executionPhases) {
    const input = {
      state: 'running', stage: progress < 58 ? 'preparing' : 'applying', progress,
      current_step: `ar_${phase}`
    };
    assert.equal(workflowFlow(input).find((node) => node.state === 'active')?.key, phase);
    assert.equal(workflowFlow({
      ...input,
      current_step: '',
      actions: [{ name: `ar_${phase}`, state: 'queued', error_message: '' }]
    }).find((node) => node.state === 'active')?.key, phase);
  }
});
