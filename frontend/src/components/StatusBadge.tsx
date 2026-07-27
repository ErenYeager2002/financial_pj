const STATE_LABELS: Record<string, string> = {
  created: '已创建',
  validating: '正在校验',
  queued: '排队中',
  waiting_confirmation: '等待确认',
  waiting_user_action: '等待人工操作',
  running: '执行中',
  succeeded: '已完成',
  failed: '失败',
  timed_out: '已超时',
  cancelled: '已取消',
}

export function StatusBadge({ state }: { state: string }) {
  return (
    <span className={`status-badge status-${state}`}>
      <span className="status-dot" aria-hidden="true" />
      {STATE_LABELS[state] || state}
    </span>
  )
}

export function stateLabel(state: string): string {
  return STATE_LABELS[state] || state
}

