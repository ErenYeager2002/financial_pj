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
  step_error_detail?: Record<string, unknown>;
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

// Presentation of backend/app/ar_execution_contract.py's pinned v2 phases.
// Keep the legacy flow separate: existing tasks retain their original snapshot.
const EXECUTION_NODES = [
  { key: 'inspect_materials', label: '检查本次材料', group: 'checks' },
  { key: 'classify_receipts', label: '生成首次判定', group: 'checks' },
  { key: 'review_order_evidence', label: '核对逐单依据', group: 'checks' },
  { key: 'validate_reconciliation', label: '校验写入计划', group: 'checks' },
  { key: 'build_initial_report', label: '生成首次核销日清', group: 'processing' },
  { key: 'stage_reconciliation', label: '准备写入暂存', group: 'processing' },
  { key: 'write_ledger', label: '写入盈亏并回读', group: 'processing' },
  { key: 'write_receipt_flow', label: '登记及回填流转', group: 'processing' },
  { key: 'verify_reconciliation', label: '写后业务复核', group: 'processing' },
  { key: 'rescan_holds', label: '重扫挂账', group: 'processing' },
  { key: 'build_final_report', label: '生成最终核销日清', group: 'processing' },
  { key: 'review_final_report', label: '核对最终清单与原因', group: 'processing' },
  { key: 'publish_reconciliation', label: '发布已复核材料', group: 'completed' },
  { key: 'complete_reconciliation', label: '核对发布并登记正式台账', group: 'completed' }
];

const EXECUTION_FLOW_NODES = [
  ...FLOW_NODES.slice(0, 4),
  ...EXECUTION_NODES.map(({ key, label }) => ({ key, label })),
  ...FLOW_NODES.slice(-2)
];

const EXECUTION_FLOW_GROUPS = FLOW_GROUPS.map((group) => ({
  ...group,
  nodeKeys:
    group.key === 'materials' || group.key === 'fetch'
      ? group.nodeKeys
      : [
          ...EXECUTION_NODES.filter((node) => node.group === group.key).map((node) => node.key),
          ...(group.key === 'completed' ? ['finalize_batch', 'completed'] : [])
        ]
}));

function flowDefinition(input: WorkflowFlowInput) {
  const usesExecutionFlow =
    EXECUTION_NODES.some(
      (node) =>
        input.current_step === `ar_${node.key}` ||
        (node.key === input.current_step && !FLOW_NODES.some((legacy) => legacy.key === node.key))
    ) ||
    input.actions?.some((action) => EXECUTION_NODES.some((node) => action.name === `ar_${node.key}`));
  return usesExecutionFlow
    ? { nodes: EXECUTION_FLOW_NODES, groups: EXECUTION_FLOW_GROUPS }
    : { nodes: FLOW_NODES, groups: FLOW_GROUPS };
}

function stepKey(input: WorkflowFlowInput, nodes: Array<{ key: string; label: string }>): string {
  if (input.stage === 'completed' || input.state === 'succeeded') return 'completed';
  const knownStep = (key: string | undefined) => nodes.some((node) => node.key === key);
  if (input.current_step && knownStep(input.current_step)) return input.current_step;
  // Initialization still uses the shared pre-execution step name. Failures
  // before a phase starts can instead carry the ar_* action name.
  if (nodes === EXECUTION_FLOW_NODES) {
    const phase = input.current_step?.replace(/^ar_/, '');
    if (phase && knownStep(phase)) return phase;
    if (input.current_step === 'inspect_inputs') return 'inspect_materials';
    const states = input.state === 'failed' || input.stage === 'failed'
      ? ['failed']
      : ['running', 'queued'];
    for (const state of states) {
      const action = input.actions?.find(
        (item) => item.state === state && item.name.startsWith('ar_') && knownStep(item.name.slice(3))
      );
      if (action) return action.name.slice(3);
    }
  }
  if (input.stage === 'awaiting_fetched_data_confirmation') return 'review_fetched_data';
  if (input.stage === 'supplementing_fetched_data') return 'fetch_zhiyun';
  if (input.stage === 'awaiting_apply_confirmation' || input.stage === 'waiting_approval') {
    return 'awaiting_confirmation';
  }
  if (input.stage === 'applying') {
    return nodes === EXECUTION_FLOW_NODES ? 'stage_reconciliation' : 'write_files';
  }
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
  const { nodes } = flowDefinition(input);
  const current = stepKey(input, nodes);
  const currentIndex = nodes.findIndex((node) => node.key === current);
  const failed = input.state === 'failed' || input.stage === 'failed';
  return nodes.map((node, index) => ({
    ...node,
    label:
      node.key === 'awaiting_confirmation' &&
      (input.stage === 'waiting_approval' || input.state === 'waiting_approval')
        ? '等待管理员审批'
        : node.label,
    state:
      failed && index === currentIndex
        ? 'error'
        : index < currentIndex || input.stage === 'completed' || input.state === 'succeeded'
          ? 'complete'
          : index === currentIndex
            ? 'active'
            : 'pending'
  }));
}

export function workflowSummaryFlow(input: WorkflowFlowInput): WorkflowFlowGroup[] {
  const { nodes, groups } = flowDefinition(input);
  const current = stepKey(input, nodes);
  const currentGroupIndex = groups.findIndex((group) => group.nodeKeys.includes(current));
  const failed = input.state === 'failed' || input.stage === 'failed';
  return groups.map((group, groupIndex) => {
    return {
      ...group,
      state:
        failed && groupIndex === currentGroupIndex
          ? 'error'
          : input.stage === 'completed' || input.state === 'succeeded' || groupIndex < currentGroupIndex
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
  const { nodes } = flowDefinition(input);
  const current = stepKey(input, nodes);
  const detail = input.step_error_detail ?? {};
  const result: { step: string; message: string; reason?: string } = {
    step:
      (typeof detail.step === 'string' ? detail.step : '') ||
      input.current_step_label ||
      nodes.find((node) => node.key === current)?.label ||
      current,
    message
  };
  if (typeof detail.reason === 'string' && detail.reason) result.reason = detail.reason;
  return result;
}
