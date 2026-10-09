'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import type { ArAttemptProcessDetailsRead, ArExecutionRead } from '@/features/platform-api/generated';

const PHASES: Record<string, string> = {
  write_ledger: '写入盈亏并回读', write_receipt_flow: '写入到账流转表',
  publish_reconciliation: '发布本日材料', complete_reconciliation: '登记核销完成'
};
const REASONS: Record<string, string> = {
  context_invalid: '任务上下文无法读取', index_invalid: '原执行索引校验未通过',
  attempt_unregistered: '执行次数尚未登记', prepared_refs_missing: '准备引用缺失',
  binding_invalid: '原执行绑定不一致', terminal_refs_missing: '原终止引用缺失',
  terminal_refs_conflict: '原终止引用无法唯一对应', fact_missing: '已登记事实文件缺失',
  fact_invalid: '事实文件核验未通过', directory_extra: '发现未登记或非法目录内容',
  scan_truncated: '本次目录检查未覆盖全部内容', budget_exceeded: '超过本次检查上限',
  identity_unconfirmed: '当前进程身份无法核实', non_effect_unanchored: '其他步骤尚未登记完整进程引用',
  investigation_unanchored: '独立调查尚未登记完整进程引用'
};
const STATES: Record<string, string> = { verified: '登记事实已核验', unknown: '证据不足', invalid: '证据校验未通过' };
const LIVENESS: Record<string, string> = {
  running: '原进程当前仍存活', not_running: '当前查询未发现原进程',
  exited_unreaped: '原进程退出但尚未回收', identity_changed: '当前身份与原记录不同',
  different_scope: '无法在原执行空间查询', not_recorded: '未登记可查询身份', unavailable: '当前身份查询不可用'
};
function count(value: number | null | undefined): string { return value == null ? '无法核实' : String(value); }
function reasons(codes: string[] | undefined): string {
  return codes?.map(code => REASONS[code] || '记录需要进一步核实').join('；') || '';
}

export function WorkflowAttemptProcessDetails({ workflowId, metadataFingerprint, activityKey }: {
  workflowId: string; metadataFingerprint: string; activityKey: string;
}): React.JSX.Element {
  const scope = `${workflowId}:${metadataFingerprint}:${activityKey}`;
  const currentScope = React.useRef(scope);
  currentScope.current = scope;
  const controller = React.useRef<AbortController | null>(null);
  const disclosure = React.useRef<HTMLDetailsElement | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [observation, setObservation] = React.useState<{ scope: string; details: ArAttemptProcessDetailsRead } | null>(null);
  const details = observation?.scope === scope ? observation.details : null;
  React.useEffect(() => {
    controller.current?.abort(); controller.current = null;
    setBusy(false); setError(''); setObservation(null);
    return () => { controller.current?.abort(); controller.current = null; };
  }, [scope]);

  function close(): void {
    controller.current?.abort(); controller.current = null;
    setBusy(false); setError(''); setObservation(null);
  }

  React.useEffect(() => {
    const ancestors: HTMLDetailsElement[] = [];
    let ancestor = disclosure.current?.parentElement?.closest('details') ?? null;
    const onParentToggle = (event: Event): void => {
      if (!(event.currentTarget as HTMLDetailsElement).open) close();
    };
    while (ancestor) {
      ancestors.push(ancestor);
      ancestor.addEventListener('toggle', onParentToggle);
      ancestor = ancestor.parentElement?.closest('details') ?? null;
    }
    return () => ancestors.forEach(item => item.removeEventListener('toggle', onParentToggle));
  }, []);

  async function inspect(): Promise<void> {
    if (controller.current || !metadataFingerprint) return;
    const pending = new AbortController();
    controller.current = pending;
    setBusy(true); setError(''); setObservation(null);
    try {
      const response = await fetch(`/api/platform/workflows/${workflowId}/execution?include_process_details=true`, {
        cache: 'no-store', signal: pending.signal
      });
      const payload = await response.json() as ArExecutionRead & { detail?: string; message?: string };
      if (!response.ok) throw new Error(payload.detail || payload.message || '逐次进程记录读取失败。');
      if (pending.signal.aborted || currentScope.current !== scope) return;
      const value = payload.process_details;
      if (!value) throw new Error('当前运行版本尚未提供逐次进程核查。');
      if (value.metadata_snapshot_fingerprint !== metadataFingerprint) {
        throw new Error('执行记录已变化，请刷新执行记录后重新查看。');
      }
      setObservation({ scope, details: value });
    } catch (cause: unknown) {
      if (!pending.signal.aborted && currentScope.current === scope) {
        setError(cause instanceof Error ? cause.message : '逐次进程记录读取失败。');
      }
    } finally {
      if (controller.current === pending) {
        controller.current = null;
        if (currentScope.current === scope) setBusy(false);
      }
    }
  }

  return <details ref={disclosure} className='rounded-md border bg-muted/20 p-3' onToggle={event => { if (!event.currentTarget.open) close(); }}>
    <summary className='cursor-pointer font-medium'>逐次进程记录</summary>
    <div className='mt-3 space-y-3'>
      <p className='text-muted-foreground'>点击后检查原执行记录，日常刷新不会自动重查。恢复条件仍以原判断为准。</p>
      <Button variant='outline' disabled={busy || !metadataFingerprint} onClick={() => void inspect()}>
        {busy ? '正在核查…' : details ? '重新检查逐次进程记录' : '查看逐次进程记录'}
      </Button>
      {busy && <p role='status'>正在读取已登记的进程证据…</p>}
      {error && <p role='alert' className='text-destructive'>{error}</p>}
      {details && <>
        <p role='status'>{details.registered_effect_coverage_complete ? '本次已完整核查已登记引用。' : '部分原执行引用无法完整核查。'} 全流程覆盖：无法核实。</p>
        {!!details.reason_codes?.length && <p className='text-muted-foreground'>{reasons(details.reason_codes)}</p>}
        {(details.items ?? []).length === 0 ? <p className='text-muted-foreground'>暂无可核查的逐次记录。</p> : <div className='max-w-full overflow-x-auto rounded border'>
          <table className='w-full min-w-[680px] text-left text-xs'>
            <caption className='sr-only'>各次原执行的进程证据核查结果</caption>
            <thead className='bg-muted/50'><tr>{['阶段与执行次数', '核查结果', '原引用与已核验数量', '待核实事项'].map(label =>
              <th key={label} scope='col' className='px-3 py-2 font-medium'>{label}</th>)}
            </tr></thead>
            <tbody>{(details.items ?? []).map(item => <tr key={`${item.action_id}:${item.attempt ?? 'gap'}:${item.phase}`} className='border-t align-top'>
              <td className='px-3 py-2'><p>{PHASES[item.phase] || '原执行阶段'}</p><p>{item.attempt == null ? '执行次数缺失' : `第 ${item.attempt} 次`}</p>
                <p className='mt-1 font-mono text-muted-foreground' title={item.action_id}>{item.action_id.slice(0, 8)}</p></td>
              <td className='px-3 py-2'><p>{STATES[item.inspection_state]}</p>{!item.coverage_complete && <p className='text-muted-foreground'>覆盖不完整</p>}</td>
              <td className='px-3 py-2 whitespace-nowrap'><p>准备登记：{count(item.prepared_record_count)}</p><p>原终止引用：{count(item.registered_terminal_count)}</p>
                <p>直接退出核验：{count(item.direct_exit_count)}</p><p>后代域核验：{count(item.descendant_domain_count)}</p></td>
              <td className='px-3 py-2 text-muted-foreground'>{reasons(item.reason_codes) || '—'}
                {Object.entries(item.liveness ?? {}).filter(([, value]) => value > 0).map(([state, value]) =>
                  <p key={state}>{LIVENESS[state] || '当前进程身份待核实'}：{value} 次</p>)}
              </td>
            </tr>)}</tbody>
          </table>
        </div>}
        <p className='text-muted-foreground'>外部系统与财务写入结果仍须单独核对；这些记录不代表材料已解锁或核销已完成。</p>
      </>}
    </div>
  </details>;
}
