export type WorkflowFlowState = 'pending' | 'active' | 'complete' | 'error';

export interface WorkflowFlowNode {
  key: string;
  label: string;
  state: WorkflowFlowState;
}

export interface WorkflowFlowInput {
  state: string;
  stage: string;
  progress: number;
  current_step?: string;
  current_step_label?: string;
  step_error?: string;
  step_error_detail?: Record<string, string>;
  error_message?: string;
  actions?: Array<{ name: string; state: string; error_message: string }>;
}

const FLOW_NODES: Array<{ key: string; label: string }> = [
  { key: 'queued', label: '提交后台任务' },
  { key: 'copy_inputs', label: '读取材料' },
  { key: 'fetch_zhiyun', label: '智云取数' },
  { key: 'inspect_inputs', label: '检查输入文件' },
  { key: 'snapshot_sources', label: '建立校验基线' },
  { key: 'classify_receipts', label: '核销判定' },
  { key: 'validate_plan', label: '校验写入计划' },
  { key: 'build_flow_plan', label: '生成流转计划' },
  { key: 'build_worklist', label: '生成核销日清' },
  { key: 'review', label: '检查核销日清' },
  { key: 'awaiting_confirmation', label: '等待确认写入' },
  { key: 'write_files', label: '写入工作副本' },
  { key: 'completed', label: '回读并完成' }
];

function stepKey(input: WorkflowFlowInput): string {
  if (input.current_step && FLOW_NODES.some((node) => node.key === input.current_step)) {
    return input.current_step;
  }
  if (input.stage === 'completed') return 'completed';
  if (input.stage === 'awaiting_apply_confirmation' || input.stage === 'waiting_approval') {
    return 'awaiting_confirmation';
  }
  if (input.stage === 'applying') return 'write_files';
  if (input.stage === 'failed') {
    const failedAction = input.actions?.find((action) => action.state === 'failed');
    if (failedAction?.name === 'apply_confirmed') return 'write_files';
    if (failedAction?.name === 'prepare_worklist') return 'fetch_zhiyun';
  }
  return 'queued';
}

export function workflowFlow(input: WorkflowFlowInput): WorkflowFlowNode[] {
  const current = stepKey(input);
  const currentIndex = FLOW_NODES.findIndex((node) => node.key === current);
  const failed = input.state === 'failed' || input.stage === 'failed';
  return FLOW_NODES.map((node, index) => ({
    ...node,
    state:
      failed && index === currentIndex
        ? 'error'
        : index < currentIndex || input.stage === 'completed'
          ? 'complete'
          : index === currentIndex
            ? 'active'
            : 'pending'
  }));
}

export function workflowError(input: WorkflowFlowInput): {
  step: string;
  message: string;
  employee?: string;
  skill?: string;
  reason?: string;
} | null {
  const message = input.step_error || input.error_message || '';
  if (!message) return null;
  const current = stepKey(input);
  const detail = input.step_error_detail ?? {};
  const result: {
    step: string;
    message: string;
    employee?: string;
    skill?: string;
    reason?: string;
  } = {
    step:
      detail.step ||
      input.current_step_label ||
      FLOW_NODES.find((node) => node.key === current)?.label ||
      current,
    message
  };
  if (detail.employee) result.employee = detail.employee;
  if (detail.skill_name || detail.skill_id) result.skill = detail.skill_name || detail.skill_id;
  if (detail.reason) result.reason = detail.reason;
  return result;
}
