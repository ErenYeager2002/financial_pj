export type WorkflowFlowState = 'pending' | 'active' | 'complete' | 'error';

export interface WorkflowFlowNode {
  key: string;
  label: string;
  state: WorkflowFlowState;
}

export interface WorkflowFlowGroup extends WorkflowFlowNode {
  nodeKeys: string[];
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
  { key: 'queued', label: '提交任务' },
  { key: 'copy_inputs', label: '读取材料' },
  { key: 'fetch_zhiyun', label: '智云取数' },
  { key: 'review_fetched_data', label: '检查取数数据' },
  { key: 'audit_shifted_details', label: '检查跨日明细' },
  { key: 'inspect_inputs', label: '检查输入文件' },
  { key: 'snapshot_sources', label: '建立校验基线' },
  { key: 'classify_receipts', label: '核销判定' },
  { key: 'validate_plan', label: '校验写入计划' },
  { key: 'build_flow_plan', label: '生成流转计划' },
  { key: 'prefill_flow', label: '登记流转信息' },
  { key: 'snapshot_prefilled_sources', label: '记录流转校验基线' },
  { key: 'build_worklist', label: '生成核销日清' },
  { key: 'review', label: '检查核销日清' },
  { key: 'awaiting_confirmation', label: '等待确认写入' },
  { key: 'write_files', label: '写入工作副本' },
  { key: 'finalize_batch', label: '生成范围报告' },
  { key: 'completed', label: '回读并完成' }
];

const FLOW_GROUPS: Array<{ key: string; label: string; nodeKeys: string[] }> = [
  {
    key: 'materials',
    label: '准备材料',
    nodeKeys: ['queued', 'copy_inputs']
  },
  {
    key: 'fetch',
    label: '智云取数',
    nodeKeys: ['fetch_zhiyun', 'review_fetched_data']
  },
  {
    key: 'checks',
    label: '数据检查',
    nodeKeys: [
      'audit_shifted_details',
      'inspect_inputs',
      'snapshot_sources',
      'classify_receipts',
      'validate_plan'
    ]
  },
  {
    key: 'processing',
    label: '核销处理',
    nodeKeys: [
      'build_flow_plan',
      'prefill_flow',
      'snapshot_prefilled_sources',
      'build_worklist',
      'review',
      'awaiting_confirmation',
      'write_files'
    ]
  },
  { key: 'completed', label: '完成', nodeKeys: ['finalize_batch', 'completed'] }
];

function stepKey(input: WorkflowFlowInput): string {
  if (input.current_step && FLOW_NODES.some((node) => node.key === input.current_step)) {
    return input.current_step;
  }
  if (input.stage === 'completed') return 'completed';
  if (input.stage === 'awaiting_fetched_data_confirmation') return 'review_fetched_data';
  if (input.stage === 'supplementing_fetched_data') return 'fetch_zhiyun';
  if (input.stage === 'awaiting_apply_confirmation' || input.stage === 'waiting_approval') {
    return 'awaiting_confirmation';
  }
  if (input.stage === 'applying') return 'write_files';
  if (input.stage === 'finalizing') return 'finalize_batch';
  if (input.stage === 'failed') {
    const failedAction = input.actions?.find((action) => action.state === 'failed');
    if (['apply_confirmed', 'apply_material_update'].includes(failedAction?.name ?? '')) {
      return 'write_files';
    }
    if (
      [
        'prepare_worklist',
        'prepare_workspace',
        'fetch_data',
        'build_fetch_preview',
        'build_reconciliation_plan'
      ].includes(failedAction?.name ?? '')
    ) {
      return 'fetch_zhiyun';
    }
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

export function workflowSummaryFlow(input: WorkflowFlowInput): WorkflowFlowGroup[] {
  const current = stepKey(input);
  const currentGroupIndex = FLOW_GROUPS.findIndex((group) => group.nodeKeys.includes(current));
  const failed = input.state === 'failed' || input.stage === 'failed';
  return FLOW_GROUPS.map((group, groupIndex) => {
    return {
      ...group,
      state:
        failed && groupIndex === currentGroupIndex
          ? 'error'
          : input.stage === 'completed' || groupIndex < currentGroupIndex
            ? 'complete'
            : groupIndex === currentGroupIndex
              ? 'active'
              : 'pending'
    };
  });
}

export function workflowError(input: WorkflowFlowInput): {
  step: string;
  message: string;
  reason?: string;
} | null {
  const message = input.step_error || input.error_message || '';
  if (!message) return null;
  const current = stepKey(input);
  const detail = input.step_error_detail ?? {};
  const result: { step: string; message: string; reason?: string } = {
    step:
      detail.step ||
      input.current_step_label ||
      FLOW_NODES.find((node) => node.key === current)?.label ||
      current,
    message
  };
  if (detail.reason) result.reason = detail.reason;
  return result;
}
