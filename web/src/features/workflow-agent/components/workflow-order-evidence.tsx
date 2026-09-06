'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { OrderEvidencePage } from '@/features/workflow-agent/order-evidence';
import { WorkflowOrderEvidenceDetail } from './workflow-order-evidence-detail';

const LABELS: Record<string, string> = { auto: '自动判定', hold: '挂账', exception: '异常' };

export function WorkflowOrderEvidence({ workflowId, workflowState }: { workflowId: string; workflowState: string }) {
  const [opened, setOpened] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [requestQuery, setRequestQuery] = React.useState('');
  const [offset, setOffset] = React.useState(0);
  const [page, setPage] = React.useState<OrderEvidencePage | null>(null);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [refresh, setRefresh] = React.useState(0);
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({});

  React.useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    setBusy(true);
    setError('');
    setPage(null);
    const search = new URLSearchParams({ offset: String(offset), limit: '10', query: requestQuery });
    void fetch(`/api/platform/workflows/${encodeURIComponent(workflowId)}/order-evidence?${search}`, {
      signal: controller.signal, cache: 'no-store'
    }).then(async (response) => {
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.message || '判断依据加载失败。');
      if (!controller.signal.aborted) setPage(payload as OrderEvidencePage);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '判断依据加载失败。');
    }).finally(() => {
      if (!controller.signal.aborted) setBusy(false);
    });
    return () => controller.abort();
  }, [workflowId, workflowState, opened, offset, requestQuery, refresh]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>逐单判断依据</CardTitle>
        <CardDescription>查看首次判定及对应的盈亏业务行。首次判定不表示已经写入或完成最终复核。</CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        {!opened ? <Button variant='outline' onClick={() => setOpened(true)}>查看判断依据</Button> : <>
          <form className='flex flex-wrap gap-2' onSubmit={(event) => {
            event.preventDefault(); setOffset(0); setRequestQuery(query.trim()); setRefresh((value) => value + 1);
          }}>
            <input aria-label='按 SO、SOD、AR 或原因码查询' placeholder='输入 SO、SOD、AR 或原因码'
              className='min-h-10 min-w-0 flex-1 rounded-md border bg-background px-3 text-sm'
              value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} />
            <Button type='submit' variant='outline' disabled={busy}>查询</Button>
          </form>
          {busy && <p role='status' className='text-sm text-muted-foreground'>正在读取判断依据…</p>}
          {error && <p role='alert' className='text-sm text-destructive'>{error}</p>}
          {page && !page.available && <p className='text-sm text-muted-foreground'>{page.message}</p>}
          {page?.available && <>
            <p className='text-sm text-muted-foreground'>匹配 {page.total} 条判定记录；同一订单的不同回款分别保留。</p>
            {(page.records || []).map((record) => {
              return <details key={`${workflowId}:${record.record_id}`} className='rounded-md border p-3'
                onToggle={event => { const open = event.currentTarget.open; setExpanded(previous => ({ ...previous, [record.record_id]: open })); }}>
                <summary className='cursor-pointer break-words text-sm font-medium'>
                  {record.ar || '无 AR'} · {record.so || '未关联 SO'} · {record.sod || '未定位 SOD'} · {LABELS[record.initial_bucket] || record.initial_bucket}
                </summary>
                <p className='mt-3 whitespace-pre-wrap break-words text-sm'>{record.reason || '此记录未提供文字原因，需核对证据。'}</p>
                {record.code && <p className='mt-1 text-xs text-muted-foreground'>原因码：{record.code}</p>}
                {record.reason_truncated && <p className='text-xs text-muted-foreground'>原因较长，此处仅显示摘要；完整内容见下方明细。</p>}
                {expanded[record.record_id] && <WorkflowOrderEvidenceDetail key={`${workflowId}:${workflowState}:${record.record_id}:${refresh}`} workflowId={workflowId} recordId={record.record_id} />}
              </details>;
            })}
            <div className='flex gap-2'>
              <Button variant='outline' disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>上一页</Button>
              <Button variant='outline' disabled={busy || page.next_offset >= page.total} onClick={() => setOffset(page.next_offset)}>下一页</Button>
            </div>
          </>}
        </>}
      </CardContent>
    </Card>
  );
}
