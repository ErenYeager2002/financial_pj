export type ArTaskStatusView = {
  label: string;
  variant: 'default' | 'secondary' | 'destructive' | 'outline';
};

type ArTaskState = {
  state: string;
  stage?: string;
  error_message?: string;
  step_error?: string;
};

type ArTaskDates = {
  reconciliation_date?: string;
  reconciliation_dates?: string[];
};

export type ArTaskListSource = ArTaskState &
  ArTaskDates & {
    id: string;
    display_id: string;
    skill_name: string;
    progress: number;
    progress_message: string;
    updated_at: string;
    batch_id?: string | null;
  };

export type ArTaskListRow = {
  key: string;
  href: string;
  kindLabel: '批次' | '单日';
  skillName: string;
  dateLabel: string;
  status: ArTaskStatusView;
  progress: number;
  progressMessage: string;
  updatedAt: string;
  updatedLabel: string;
  displayId: string;
  failureSummary: string;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
// API serialization owns redaction. This final display guard prevents technical
// locations or credential-shaped text from being repeated in compact list rows.
const UNSAFE_PUBLIC_ERROR =
  /https?:\/\/|[A-Za-z]:[\\/]|(?:^|\s)\/(?:[^/\s]+\/)+|traceback|\bat .+\(.+:\d+:\d+\)|\b(password|passwd|secret|token|authorization|cookie)\s*[:=]/i;
const WAITING_STAGES = new Set([
  'awaiting_fetched_data_confirmation',
  'awaiting_apply_confirmation',
  'waiting_approval'
]);

const STATE_STATUS: Record<string, ArTaskStatusView> = {
  queued: { label: '等待处理', variant: 'outline' },
  active: { label: '待处理', variant: 'outline' },
  running: { label: '处理中', variant: 'default' },
  finalizing: { label: '处理中', variant: 'default' },
  cancelling: { label: '取消中', variant: 'outline' },
  waiting_confirmation: { label: '待确认', variant: 'default' },
  failed: { label: '失败', variant: 'destructive' },
  succeeded: { label: '已完成', variant: 'secondary' },
  cancelled: { label: '已取消', variant: 'outline' }
};

export function arTaskDateLabel(task: ArTaskDates): string {
  if (task.reconciliation_dates) {
    const dates = [...new Set(task.reconciliation_dates)].toSorted();
    if (!dates.length) return '业务日期未设置';
    if (dates.length === 1) return `${dates[0]} · 共 1 个核销日`;
    return `${dates.join('、')} · 共 ${dates.length} 个核销日`;
  }
  return task.reconciliation_date || '业务日期未设置';
}

export function arTaskStatus(task: ArTaskState): ArTaskStatusView {
  if (task.state === 'failed' || task.stage === 'failed') {
    return { label: '失败', variant: 'destructive' };
  }
  if (task.state === 'cancelled' || task.stage === 'cancelled') {
    return { label: '已取消', variant: 'outline' };
  }
  if (task.state === 'succeeded' || task.stage === 'completed') {
    return { label: '已完成', variant: 'secondary' };
  }
  if (WAITING_STAGES.has(task.stage ?? '')) {
    return { label: '待确认', variant: 'default' };
  }
  return STATE_STATUS[task.state] ?? { label: '状态未知', variant: 'outline' };
}

export function arTaskFailureSummary(task: ArTaskState): string {
  if (task.state !== 'failed' && task.stage !== 'failed') return '';
  const message = (task.step_error || task.error_message || '').trim();
  if (!message || UNSAFE_PUBLIC_ERROR.test(message)) {
    return '任务未完成，请进入详情查看失败步骤。';
  }
  return message.slice(0, 120);
}

export function arTaskUpdatedLabel(updatedAt: string): string {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return '时间未知';
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? '';
  return `${value('year')}-${value('month')}-${value('day')} ${value('hour')}:${value('minute')}`;
}

export function arTaskBusinessId(displayId: string, internalId: string): string {
  const candidate = displayId.trim();
  return !candidate || candidate === internalId || UUID.test(candidate) ? '' : candidate;
}

export function buildArTaskListRows(
  batches: ArTaskListSource[],
  workflows: ArTaskListSource[]
): ArTaskListRow[] {
  const entries = [
    ...batches.map((task) => ({ kind: 'batch' as const, task })),
    ...workflows
      .filter((task) => !task.batch_id)
      .map((task) => ({ kind: 'workflow' as const, task }))
  ].toSorted(
    (left, right) =>
      new Date(right.task.updated_at).getTime() - new Date(left.task.updated_at).getTime()
  );

  return entries.map(({ kind, task }) => ({
    key: `${kind}-${task.id}`,
    href: `/dashboard/workflows/${kind === 'batch' ? 'batches/' : ''}${encodeURIComponent(task.id)}`,
    kindLabel: kind === 'batch' ? '批次' : '单日',
    skillName: task.skill_name,
    dateLabel: arTaskDateLabel(task),
    status: arTaskStatus(task),
    progress: Math.min(Math.max(task.progress, 0), 100),
    progressMessage: task.progress_message || '等待更新',
    updatedAt: task.updated_at,
    updatedLabel: arTaskUpdatedLabel(task.updated_at),
    displayId: arTaskBusinessId(task.display_id, task.id),
    failureSummary: arTaskFailureSummary(task)
  }));
}
