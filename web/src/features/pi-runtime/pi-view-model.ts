export type PiConnectionState = 'connecting' | 'live' | 'recovering';
export type PiSessionFacts = {
  connection: PiConnectionState;
  running: boolean;
  mode: string;
  working: boolean;
  activityKnown: boolean;
  dialogCount: number;
  sending: boolean;
  uploading: boolean;
  uncertainDelivery: boolean;
};

/** UI availability only. Server ownership, admission and financial guards remain authoritative. */
export function projectPiSessionStatus(facts: PiSessionFacts) {
  const rpc = facts.mode === 'rpc';
  const observed = facts.connection === 'live';
  const known = observed && (!facts.running || facts.activityKnown);
  const executionState: 'unknown' | 'idle' | 'running' | 'waiting_input' = !known ? 'unknown'
    : !facts.running ? 'idle' : facts.dialogCount > 0 ? 'waiting_input'
    : facts.working ? 'running' : 'idle';
  const message = facts.connection === 'connecting' ? '正在连接会话…'
    : facts.connection === 'recovering' ? '连接中断，正在恢复；后台任务可能仍在运行。'
    : facts.running && !rpc ? facts.mode === 'terminal' ? '此会话正在辅助终端运行，请先结束终端环境再继续对话。' : '正在确认会话运行模式…'
    : !known ? '正在同步会话状态…' : '';
  return {
    connectionState: facts.connection,
    executionState,
    activityLabel: executionState === 'unknown' ? '等待状态恢复'
      : executionState === 'waiting_input' ? '等待你的回复'
      : facts.sending ? '正在发送…' : executionState === 'running' ? '正在处理…' : '等待继续',
    submitLabel: facts.sending ? executionState === 'waiting_input' ? '等待回复' : '发送中'
      : facts.working ? '发送补充' : '发送消息',
    message,
    canSend: known && (!facts.running || rpc) && !facts.sending && !facts.uploading && !facts.uncertainDelivery,
    canConfigure: known && rpc && facts.running && !facts.working && facts.dialogCount === 0,
    canInterrupt: known && rpc && facts.running && facts.working,
    canReplyToDialog: known && rpc && facts.running && facts.dialogCount > 0,
    canManageEnvironment: observed
  };
}
