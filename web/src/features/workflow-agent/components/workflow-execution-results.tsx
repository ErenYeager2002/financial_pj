'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import type { ArExecutionRead, ArRecoveryRequest } from '@/features/platform-api/generated';
import type { WorkflowRead } from '@/features/platform-api/types';

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

  if (!error && result?.available === false) return null;
  const investigations = result?.phases?.filter(phase => text(object(phase.investigation).failed_action_id)) ?? [];
  return (
    <details className='rounded-lg border px-4 py-3'>
      <summary className='cursor-pointer text-sm font-medium'>恢复处理</summary>
      <div className='mt-3 space-y-3 text-sm'>
        {error && <p role='alert' className='text-destructive'>{error}</p>}
        {!result && !error && <p role='status'>正在读取恢复条件…</p>}
        {result?.recovery_reason && <p>{result.recovery_reason}</p>}
        {investigations.map((phase, index) => (
          <Investigation key={text(phase.name) || index} value={phase.investigation}
            busy={busy} onInvestigate={investigate} onCancel={cancelInvestigation} />
        ))}
        <div className='flex flex-wrap gap-2'>
          <Button variant='outline' disabled={busy} onClick={() => setRevision(value => value + 1)}>刷新恢复条件</Button>
          {result?.recovery_allowed && <Button disabled={busy} onClick={() => void recover()}>
            {busy ? '正在恢复…' : '恢复未完成阶段'}
          </Button>}
        </div>
      </div>
    </details>
  );
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
