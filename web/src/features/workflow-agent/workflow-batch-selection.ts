import type { WorkflowRead } from '@/features/platform-api/types';

const TERMINAL_STATES = new Set(['succeeded', 'failed', 'cancelled']);
const ATTENTION_STAGES = new Set([
  'awaiting_fetched_data_confirmation',
  'awaiting_apply_confirmation',
  'waiting_approval'
]);

type WorkflowBatchSelection = {
  state: string;
  workflows: WorkflowRead[];
};

type WorkflowBatchRetryGuidance = WorkflowBatchSelection & {
  retryable: boolean;
  can_retry: boolean;
  retry_message: string;
  retry_block_reason: string;
};

export type BatchFailureGuidance = {
  failedDate: string;
  failedStep: string;
  laterDatesMessage: string;
  nextAction: string;
};

export function isTerminalWorkflow(workflow: WorkflowRead): boolean {
  return TERMINAL_STATES.has(workflow.state) || workflow.stage === 'completed';
}

export function isWaitingWorkflow(workflow: WorkflowRead): boolean {
  return workflow.state === 'queued' || workflow.stage === 'queued';
}

export function needsWorkflowAttention(workflow: WorkflowRead): boolean {
  return workflow.state === 'waiting_confirmation' || ATTENTION_STAGES.has(workflow.stage);
}

export function batchFetchedDataWorkflow(workflows: WorkflowRead[]): WorkflowRead | null {
  return (
    workflows.find(
      (workflow) =>
        workflow.fetched_data_available && workflow.stage === 'awaiting_fetched_data_confirmation'
    ) ??
    workflows.find((workflow) => workflow.fetched_data_available) ??
    null
  );
}

export function workflowStatusLabel(workflow: WorkflowRead): string {
  if (workflow.state === 'succeeded' || workflow.stage === 'completed') return '已完成';
  if (workflow.state === 'failed' || workflow.stage === 'failed') return '失败';
  if (workflow.state === 'cancelled' || workflow.stage === 'cancelled') return '已取消';
  if (workflow.stage === 'awaiting_fetched_data_confirmation') return '待检查取数';
  if (workflow.stage === 'awaiting_apply_confirmation' || workflow.stage === 'waiting_approval') {
    return '待确认写入';
  }
  if (workflow.state === 'waiting_confirmation') return '待确认写入';
  if (workflow.state === 'running' || workflow.state === 'cancelling') return '处理中';
  return '等待';
}

export function workflowStepLabel(workflow: WorkflowRead): string {
  if (workflow.current_step_label) return workflow.current_step_label;
  if (workflow.stage === 'queued') {
    return workflow.batch_sequence > 1 ? '等待前一天完成' : '等待开始';
  }
  if (workflow.stage === 'awaiting_fetched_data_confirmation') return '检查智云取数';
  if (workflow.stage === 'awaiting_apply_confirmation' || workflow.stage === 'waiting_approval') {
    return '等待确认写入';
  }
  if (workflow.stage === 'completed') return '已完成';
  if (workflow.stage === 'failed') return '查看失败步骤';
  return workflow.progress_message || '等待后台 Worker';
}

export function workflowAttentionHint(workflow: WorkflowRead): string {
  if (workflow.state === 'failed' || workflow.stage === 'failed') {
    return '该日期未完成，请查看失败步骤';
  }
  if (workflow.stage === 'awaiting_fetched_data_confirmation') return '等待检查取数数据';
  if (workflow.stage === 'awaiting_apply_confirmation' || workflow.stage === 'waiting_approval') {
    return '等待确认写入';
  }
  if (isWaitingWorkflow(workflow) && workflow.batch_sequence > 1) return '等待前一天完成';
  return '';
}

export function preferredWorkflow(workflows: WorkflowRead[]): WorkflowRead | null {
  return (
    workflows.find(needsWorkflowAttention) ??
    workflows.find((workflow) => workflow.state === 'running') ??
    workflows.find((workflow) => workflow.state === 'failed' || workflow.stage === 'failed') ??
    workflows.find((workflow) => !isTerminalWorkflow(workflow)) ??
    workflows.at(-1) ??
    null
  );
}

export function preferredWorkflowForBatch(batch: WorkflowBatchSelection): WorkflowRead | null {
  if (batch.state === 'failed') {
    return (
      batch.workflows.find(
        (workflow) => workflow.state === 'failed' || workflow.stage === 'failed'
      ) ??
      batch.workflows.at(-1) ??
      null
    );
  }
  if (TERMINAL_STATES.has(batch.state)) return batch.workflows.at(-1) ?? null;
  return preferredWorkflow(batch.workflows);
}

export function currentWorkflow(workflows: WorkflowRead[]): WorkflowRead | null {
  return (
    workflows.find((workflow) => workflow.state === 'running') ??
    workflows.find(needsWorkflowAttention) ??
    workflows.find((workflow) => !isTerminalWorkflow(workflow)) ??
    null
  );
}

export function currentWorkflowForBatch(batch: WorkflowBatchSelection): WorkflowRead | null {
  if (TERMINAL_STATES.has(batch.state)) return null;
  return currentWorkflow(batch.workflows);
}

export function workflowStatusInBatch(
  batchState: string,
  workflows: WorkflowRead[],
  workflow: WorkflowRead
): string {
  if (batchState === 'succeeded') return '已完成';
  if (batchState === 'cancelled') {
    return workflow.state === 'succeeded' || workflow.stage === 'completed' ? '已完成' : '已取消';
  }
  if (batchState === 'failed') {
    if (workflow.state === 'succeeded' || workflow.stage === 'completed') return '已完成';
    if (workflow.state === 'failed' || workflow.stage === 'failed') return '失败';
    const failedSequence = workflows.find(
      (item) => item.state === 'failed' || item.stage === 'failed'
    )?.batch_sequence;
    if (failedSequence !== undefined && workflow.batch_sequence > failedSequence) return '未开始';
    return '已暂停';
  }
  return workflowStatusLabel(workflow);
}

export function batchFailureGuidance(
  batch: WorkflowBatchRetryGuidance
): BatchFailureGuidance | null {
  if (batch.state !== 'failed') return null;
  const failed = batch.workflows.find(
    (workflow) => workflow.state === 'failed' || workflow.stage === 'failed'
  );
  if (!failed) {
    return {
      failedDate: '失败日期待确认',
      failedStep: '失败步骤待确认',
      laterDatesMessage: '批次已经停止，后续日期不会继续处理。',
      nextAction: batch.can_retry
        ? '可以安全重试；已成功日期不会重复执行。'
        : batch.retry_block_reason || batch.retry_message || '当前失败阶段不支持自动重试。'
    };
  }
  const laterCount = batch.workflows.filter(
    (workflow) =>
      workflow.batch_sequence > failed.batch_sequence &&
      workflow.state !== 'succeeded' &&
      workflow.stage !== 'completed'
  ).length;
  return {
    failedDate: failed.reconciliation_date || '失败日期待确认',
    failedStep: failed.current_step_label || failed.step_error_detail?.step || '失败步骤待确认',
    laterDatesMessage: laterCount
      ? `${laterCount} 个后续日期已经暂停，尚未开始。`
      : '没有后续未处理日期。',
    nextAction: batch.can_retry
      ? `${batch.retry_message || '可以从失败日期继续。'} 已成功日期不会重复执行。`
      : batch.retry_block_reason || batch.retry_message || '当前失败阶段不支持自动重试。'
  };
}
