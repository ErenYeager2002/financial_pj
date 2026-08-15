export const TERMINAL_RUN_STATES = new Set(['succeeded', 'failed', 'timed_out', 'cancelled']);

const STATE_LABELS: Record<string, string> = {
  created: '已创建',
  validating: '校验中',
  waiting_confirmation: '等待确认',
  queued: '排队中',
  running: '处理中',
  cancelling: '正在取消',
  succeeded: '已完成',
  failed: '失败',
  timed_out: '已超时',
  cancelled: '已取消'
};

const FIELD_LABELS: Record<string, string> = {
  bank_records: '银行流水数',
  ledger_records: '总账记录数',
  matched: '成功匹配',
  unmatched_bank: '待核查流水',
  unmatched_ledger: '待核查总账',
  output_count: '输出文件数',
  processed: '已处理',
  skipped: '已跳过',
  errors: '错误数'
};

export function runStateLabel(state: string): string {
  return STATE_LABELS[state] ?? state;
}

export function runStateVariant(
  state: string
): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (state === 'succeeded') return 'default';
  if (state === 'failed' || state === 'timed_out') return 'destructive';
  if (state === 'running' || state === 'queued') return 'secondary';
  return 'outline';
}

export function resultFieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key.replaceAll('_', ' ');
}
