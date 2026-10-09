'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import type { ArAttemptHistoryRead, ArExecutionRead, ArRecoveryRequest } from '@/features/platform-api/generated';
import type { WorkflowRead } from '@/features/platform-api/types';
import { WorkflowAttemptProcessDetails } from './workflow-attempt-process-details';

const STATES: Record<string, string> = { succeeded: '已完成', running: '执行中', queued: '等待执行', pending: '尚未执行', failed: '未完成', cancelled: '已取消', verified: '已核对', rolled_back: '改动已恢复原样' };
function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
export function WorkflowRecoveryActions({ workflow, onRecovered }: { workflow: WorkflowRead; onRecovered: () => Promise<void> }): React.JSX.Element | null {
  const [result, setResult] = React.useState<ArExecutionRead | null>(null);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [revision, setRevision] = React.useState(0);
  const [abandonment, setAbandonment] = React.useState<{ allowed: boolean; abandoned: boolean; reason: string; checkpoint_fingerprint: string } | null>(null);
  const [confirmAbandon, setConfirmAbandon] = React.useState(false);
  React.useEffect(() => {
    const controller = new AbortController();
    setAbandonment(null); setConfirmAbandon(false);
    void fetch(`/api/platform/workflows/${workflow.id}/execution/abandon`, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || payload.message || '读取放弃条件失败。');
        if (!controller.signal.aborted) setAbandonment(payload);
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '读取放弃条件失败。');
      });
    return () => controller.abort();
  }, [workflow.id, workflow.state, revision]);

  async function abandonResult(): Promise<void> {
    if (!abandonment?.allowed) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/platform/workflows/${workflow.id}/execution/abandon`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkpoint_fingerprint: abandonment.checkpoint_fingerprint })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.message || '放弃未发布结果失败。');
      setAbandonment(payload); setConfirmAbandon(false); setRevision(value => value + 1);
      await onRecovered();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '放弃未发布结果失败。'); }
    finally { setBusy(false); }
  }
  React.useEffect(() => {
    const controller = new AbortController();
    setError('');
    void fetch(`/api/platform/workflows/${workflow.id}/execution`, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || payload.message || '执行记录加载失败。');
        if (!controller.signal.aborted) setResult(payload as ArExecutionRead);
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '执行记录加载失败。');
      });
    return () => controller.abort();
  }, [workflow.id, workflow.state, workflow.progress, workflow.progress_message, revision]);

  const investigationRunning = result?.phases?.some(phase => ['queued', 'running'].includes(text(object(phase.investigation).state)));
  React.useEffect(() => {
    if (!investigationRunning) return;
    const timer = setTimeout(() => setRevision(value => value + 1), 3000);
    return () => clearTimeout(timer);
  }, [investigationRunning, result]);

  async function investigate(value: unknown): Promise<void> {
    const investigation = object(value);
    if (investigation.allowed !== true) return;
    setBusy(true); setError('');
    try {
      const body: ArRecoveryRequest = { failed_action_id: text(investigation.failed_action_id), checkpoint_fingerprint: text(investigation.checkpoint_fingerprint) };
      const response = await fetch(`/api/platform/workflows/${workflow.id}/execution/investigate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.message || '独立调查未启动。');
      setResult(payload as ArExecutionRead);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '独立调查未启动。'); }
    finally { setBusy(false); }
  }

  async function cancelInvestigation(): Promise<void> {
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/platform/workflows/${workflow.id}/cancel`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.message || '调查取消请求未完成。');
      setRevision(value => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '调查取消请求未完成。'); }
    finally { setBusy(false); }
  }

  async function recover(): Promise<void> {
    if (!result?.recovery_allowed) return;
    setBusy(true); setError('');
    try {
      const body: ArRecoveryRequest = { failed_action_id: result.recovery_failed_action_id, checkpoint_fingerprint: result.checkpoint_fingerprint };
      const response = await fetch(`/api/platform/workflows/${workflow.id}/execution/recover`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.message || '恢复请求未完成。');
      setResult(payload as ArExecutionRead);
      await onRecovered();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '恢复请求未完成。'); }
    finally { setBusy(false); }
  }

  if (!error && result?.available === false && !result.attempt_history) return null;
  const executionAvailable = result?.available !== false;
  const investigations = result?.phases?.filter(phase => text(object(phase.investigation).failed_action_id)) ?? [];
  return (
    <details className='rounded-lg border px-4 py-3'>
      <summary className='cursor-pointer text-sm font-medium'>{executionAvailable ? '恢复处理' : '执行记录'}</summary>
      <div className='mt-3 space-y-3 text-sm'>
        {error && <p role='alert' className='text-destructive'>{error}</p>}
        {!result && !error && <p role='status'>正在读取恢复条件…</p>}
        {result?.attempt_history && <AttemptHistory history={result.attempt_history} />}
        {result?.attempt_history && <WorkflowAttemptProcessDetails key={workflow.id} workflowId={workflow.id}
          metadataFingerprint={result.attempt_history.snapshot_fingerprint}
          activityKey={`${workflow.state}:${workflow.progress}:${workflow.progress_message}:${revision}`} />}
        {!executionAvailable && <p className='text-muted-foreground'>这份历史任务不支持当前恢复流程，仅提供执行记录查看。</p>}
        {abandonment?.abandoned ? <p role='status'>{abandonment.reason}</p> : result?.recovery_reason && <p>{result.recovery_reason}</p>}
        {!abandonment?.abandoned && abandonment && <p className='text-muted-foreground'>{abandonment.reason}</p>}
        {executionAvailable && abandonment?.allowed && (confirmAbandon ? <div className='space-y-2 rounded border p-3'>
          <p>确认放弃失败当天的未发布改动？此前成功日期的材料会保留，暂存和失败记录会封存，后续未执行日期会取消。旧任务不能再恢复，可换表或新建任务。</p>
          <Button variant='destructive' disabled={busy} onClick={() => void abandonResult()}>{busy ? '正在处置…' : '确认放弃并解锁材料'}</Button>
          <Button variant='outline' disabled={busy} onClick={() => setConfirmAbandon(false)}>返回</Button>
        </div> : <Button variant='outline' disabled={busy} onClick={() => setConfirmAbandon(true)}>放弃未发布结果并解锁材料</Button>)}
        {executionAvailable && investigations.map((phase, index) => (
          <Investigation key={text(phase.name) || index} value={phase.investigation}
            busy={busy} onInvestigate={investigate} onCancel={cancelInvestigation} />
        ))}
        <div className='flex flex-wrap gap-2'>
          <Button variant='outline' disabled={busy} onClick={() => setRevision(value => value + 1)}>{executionAvailable ? '刷新恢复条件' : '刷新执行记录'}</Button>
          {executionAvailable && result?.recovery_allowed && <Button disabled={busy} onClick={() => void recover()}>
            {busy ? '正在恢复…' : '恢复未完成阶段'}
          </Button>}
        </div>
      </div>
    </details>
  );
}


const HISTORY_PHASES: Record<string, string> = {
  write_ledger: '写入盈亏并回读', write_receipt_flow: '写入到账流转表',
  publish_reconciliation: '发布本日材料', complete_reconciliation: '登记核销完成'
};
const HISTORY_STATES: Record<string, string> = {
  intent_recorded: '启动意图已登记，结果待核清', phase_completed: '阶段完成已登记',
  legacy_unknown: '历史记录缺失'
};
const HISTORY_REASONS: Record<string, string> = {
  context_invalid: '任务上下文无法读取', index_invalid: '执行索引校验未通过',
  index_missing: '尚未登记执行索引', action_metadata_invalid: '动作状态记录无法核实', action_missing: '原动作记录缺失',
  action_identity_invalid: '动作编号无法核实', action_identity_conflict: '动作身份记录冲突',
  action_phase_mismatch: '动作与已登记阶段不一致', action_counter_invalid: '执行次数无法核实',
  attempt_identity_conflict: '执行次数或身份绑定冲突', attempt_history_missing: '部分执行未登记历史',
  timestamp_invalid: '执行时间无法核实', action_scan_truncated: '动作数量超过本次查询上限',
  history_output_truncated: '记录数量超过本次展示上限'
};
function historyTime(value: string | null | undefined): string {
  if (!value) return '未登记';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '时间待核实';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(date);
}
function historyReasons(codes: string[] | undefined): string {
  return codes?.map(code => HISTORY_REASONS[code] || '记录需要核实').join('；') || '';
}
function AttemptHistory({ history }: { history: ArAttemptHistoryRead }): React.JSX.Element {
  const items = history.items ?? [];
  return <details className='rounded-md border bg-muted/20 p-3'>
    <summary className='cursor-pointer font-medium'>历史执行记录 · 已登记 {history.registered_attempt_count} 次
      {!history.metadata_coverage_complete && <span className='ml-2 text-muted-foreground'>记录不完整</span>}
    </summary>
    <div className='mt-3 space-y-3'>
      <p className='text-muted-foreground'>仅展示执行记录；不代表进程已停止、核销已完成或材料已解锁。时间为北京时间。</p>
      <p>未登记次数：{history.missing_attempt_count == null ? '无法核实' : history.missing_attempt_count}；本次查看 {history.scanned_action_count} 条动作记录。</p>
      {!history.metadata_coverage_complete && <p role='status' className='rounded border border-amber-500/40 bg-amber-500/10 p-2'>
        {historyReasons(history.reason_codes) || '历史记录不完整，需要进一步核实。'}
      </p>}
      {items.length === 0 ? <p className='text-muted-foreground'>暂无可展示的执行记录。</p> :
        <div className='max-w-full overflow-x-auto rounded border'>
          <table className='w-full min-w-[720px] text-left text-xs'>
            <caption className='sr-only'>各次执行的原始登记事实与历史缺口</caption>
            <thead className='bg-muted/50'><tr>
              {['阶段与动作', '执行次数', '原材料', '登记状态', '登记时间', '待核实事项'].map(label =>
                <th key={label} scope='col' className='px-3 py-2 font-medium'>{label}</th>)}
            </tr></thead>
            <tbody>{items.map(item => <tr key={`${item.action_id}:${item.attempt ?? 'gap'}:${item.phase}`} className='border-t align-top'>
              <td className='px-3 py-2'><p>{HISTORY_PHASES[item.phase]}</p><p title={item.action_id} className='mt-1 font-mono text-muted-foreground'>{item.action_id.slice(0, 8)}</p></td>
              <td className='px-3 py-2 whitespace-nowrap'>{item.attempt == null ? '次数记录缺失' : `第 ${item.attempt} 次`}
                {item.record_state === 'legacy_unknown' && <p className='mt-1 text-muted-foreground'>缺少 {item.missing_attempt_count == null ? '未知' : item.missing_attempt_count} 次</p>}
              </td>
              <td className='px-3 py-2'>{item.material_version == null ? '无法核实' : `V${item.material_version}`}</td>
              <td className='px-3 py-2'>{HISTORY_STATES[item.record_state]}</td>
              <td className='px-3 py-2 whitespace-nowrap'><p>意图登记：{historyTime(item.intent_at)}</p>
                {item.record_state === 'phase_completed' && <p>完成登记：{historyTime(item.completed_at)}</p>}</td>
              <td className='px-3 py-2 text-muted-foreground'>{historyReasons(item.reason_codes) || '—'}</td>
            </tr>)}</tbody>
          </table>
        </div>}
    </div>
  </details>;
}

function Investigation({ value, busy, onInvestigate, onCancel }: { value: unknown; busy: boolean; onInvestigate: (value: unknown) => Promise<void>; onCancel: () => Promise<void> }): React.JSX.Element {
  const investigation = object(value);
  const summary = object(investigation.summary);
  const items = Array.isArray(summary.items) ? summary.items : [];
  return <div className='mt-2 space-y-2 border-t pt-2'>
    <p className='font-medium'>独立业务调查：{STATES[text(investigation.state)] || '尚未开始'}</p>
    <p>{text(investigation.reason)}</p>
    {text(investigation.action_error) && <p className='text-destructive'>{text(investigation.action_error)}</p>}
    {text(summary.message) && <p>{text(summary.message)}</p>}
    {items.map((value, index) => {
      const item = object(value);
      const problems = Array.isArray(item.row_problems) ? item.row_problems : [];
      return <div key={index}>
        <p>{text(item.label)}：{text(item.message)}{typeof item.row_problem_count === 'number' && item.row_problem_count > 0 ? `（单元格问题 ${item.row_problem_count} 项）` : ''}</p>
        {problems.length > 0 && <details className='mt-1'>
          <summary className='cursor-pointer'>查看差异位置和原因</summary>
          <p className='text-muted-foreground'>列出回读位置和检查项；原始单元格值不在此展示。</p>
          <ul className='list-disc space-y-1 pl-5'>
            {problems.map((value, problemIndex) => {
              const problem = object(value);
              return <li key={problemIndex}>
                {typeof problem.row === 'number' ? `第 ${problem.row} 行 ` : ''}
                {text(problem.field)}{text(problem.case_id)}：{text(problem.message)}
              </li>;
            })}
          </ul>
          {typeof item.row_problem_count === 'number' && item.row_problem_count > problems.length &&
            <p>当前展示前 {problems.length} 项，共 {item.row_problem_count} 项。</p>}
        </details>}
        {problems.length === 0 && typeof item.row_problem_count === 'number' && item.row_problem_count > 0 &&
          <p className='text-muted-foreground'>这份历史调查仅登记了问题数量，未登记可展示的逐项位置。</p>}
      </div>;
    })}
    {text(summary.process_message) && <p className='text-muted-foreground'>{text(summary.process_message)}</p>}
    {investigation.allowed === true && <Button variant='outline' disabled={busy} onClick={() => void onInvestigate(value)}>
      {busy ? '正在提交…' : '调查实际写入结果'}
    </Button>}
    {investigation.cancel_allowed === true && <Button variant='outline' disabled={busy} onClick={() => void onCancel()}>停止调查</Button>}
  </div>;
}
