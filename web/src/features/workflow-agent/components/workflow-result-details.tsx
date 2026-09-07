'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { ArResultPage } from '@/features/platform-api/generated';

export const RESULT_CATEGORIES = [
  ['written', '已写入'], ['skipped', '已跳过'], ['hold', '挂账'],
  ['conflict', '冲突'], ['exception', '异常']
] as const;
export type ResultFilter = typeof RESULT_CATEGORIES[number][0];
const LABELS = Object.fromEntries(RESULT_CATEGORIES);
export const RESULT_COLORS: Record<ResultFilter, { text: string; surface: string }> = {
  written: {
    text: 'text-emerald-700 dark:text-emerald-300',
    surface: 'border-emerald-600/30 bg-emerald-50 dark:bg-emerald-950/30'
  },
  skipped: {
    text: 'text-slate-600 dark:text-slate-300',
    surface: 'border-slate-500/30 bg-slate-50 dark:bg-slate-800/40'
  },
  hold: {
    text: 'text-amber-700 dark:text-amber-300',
    surface: 'border-amber-600/30 bg-amber-50 dark:bg-amber-950/30'
  },
  conflict: {
    text: 'text-violet-700 dark:text-violet-300',
    surface: 'border-violet-600/30 bg-violet-50 dark:bg-violet-950/30'
  },
  exception: {
    text: 'text-red-700 dark:text-red-300',
    surface: 'border-red-600/30 bg-red-50 dark:bg-red-950/30'
  }
};

function CopyNumber({ value, label }: { value: string; label: string }) {
  const [message, setMessage] = useState('');
  return <span className='inline-flex max-w-full flex-wrap items-center gap-1'>
    {!value && <span className='text-xs'>{label} 未识别</span>}
    {value && <button type='button' className='min-h-11 min-w-11 break-all text-left font-mono text-xs hover:text-primary focus-visible:outline-2 focus-visible:outline-ring'
      aria-label={`复制${label} ${value}`} title='点击复制' onClick={async () => {
        try { await navigator.clipboard.writeText(value); setMessage('已复制'); }
        catch { setMessage('复制失败，请选择编号复制'); }
      }}>{value}</button>}
    {message && <span role='status' className='text-xs text-muted-foreground'>{message}</span>}
  </span>;
}

function StatusBadges({ categories }: { categories: ResultFilter[] }) {
  return <span className='inline-flex flex-wrap gap-1'>
    {categories.map(category => <Badge key={category} variant='outline' className={`${RESULT_COLORS[category].text} ${RESULT_COLORS[category].surface}`}>{LABELS[category]}</Badge>)}
  </span>;
}

export function WorkflowResultDetails({ id, scope, filter, onClose }: {
  id: string; scope: string; filter: ResultFilter; onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ArResultPage | null>(null);
  const [groups, setGroups] = useState<NonNullable<ArResultPage['groups']>>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError('');
    const query = new URLSearchParams({ category: filter, offset: String(offset), limit: '10' });
    const kind = scope === 'batch' ? 'workflow-batches' : 'workflows';
    void fetch(`/api/platform/${kind}/${encodeURIComponent(id)}/result-details?${query}`, {
      signal: controller.signal, cache: 'no-store'
    }).then(async response => {
      if (!response.ok) throw new Error('核销明细加载失败，请重试。');
      const result: ArResultPage = await response.json();
      if (controller.signal.aborted) return;
      setPage(result);
      setGroups(previous => offset === 0 ? result.groups || [] : [
        ...previous, ...(result.groups || []).filter(group => !previous.some(item => item.id === group.id))
      ]);
    }).catch(() => {
      if (!controller.signal.aborted) setError('核销明细加载失败，请重试。');
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [id, scope, filter, offset, retry]);

  const unavailable = page?.dates.filter(day => day.state === 'pending' || day.state === 'unavailable') || [];
  const hasReadableDates = page?.dates.some(day => day.state === 'available' || day.state === 'empty');
  return <section className='space-y-3 border-t pt-4' aria-label='核销订单明细'>
    <div className='flex flex-wrap items-center justify-between gap-2'>
      <h3 className={`text-sm font-medium ${RESULT_COLORS[filter].text}`}>{LABELS[filter]}{page && hasReadableDates ? ` · ${page.total} 组 AR / SO${unavailable.length > 0 ? '（仅已读取日期）' : ''}` : ''}</h3>
      <Button variant='ghost' size='sm' className='min-h-11' onClick={onClose}>收起</Button>
    </div>
    {unavailable.map(day => <p key={day.date} className='text-xs text-amber-700 dark:text-amber-300'>
      {day.date} · {day.message}，未计入明细
    </p>)}
    {page?.dates.filter(day => day.state === 'available' && day.message).map(day => <p key={day.date}
      className='text-xs text-amber-700 dark:text-amber-300'>{day.date} · {day.message}</p>)}
    {groups.length > 0 && <div
      className='max-h-[40rem] overflow-y-auto overscroll-contain rounded-md border focus-visible:outline-2 focus-visible:outline-ring'
      tabIndex={0} role='region' aria-label={`${LABELS[filter]}列表，最多显示五条，可上下滚动`}
      onScroll={event => {
        const box = event.currentTarget;
        if (!busy && !error && page && page.next_offset > offset && page.next_offset < page.total &&
          box.scrollHeight - box.scrollTop - box.clientHeight < 80) setOffset(page.next_offset);
      }}>
      <ul className='divide-y px-3'>
        {groups.map(group => <li key={group.id} className='min-h-32 py-2'>
            <div className='flex flex-wrap items-center gap-x-3'>
              <CopyNumber value={group.ar} label='AR 号' />
              <CopyNumber value={group.so} label='SO 号' />
              <span className='text-xs tabular-nums text-muted-foreground'>{group.date}</span>
              {group.categories.length > 1 && <StatusBadges categories={group.categories} />}
            </div>
            {group.records.length === 1 && <p className='mt-1 line-clamp-1 text-xs text-muted-foreground' title={group.records[0].reason}>{group.records[0].reason}</p>}
            <details className='mt-1'>
              <summary className='min-h-11 cursor-pointer py-3 text-xs text-primary'>查看 SOD 明细（{group.records.length}）</summary>
              <div className='space-y-3'>{group.records.map(record => <div key={record.record_id} className='border-t pt-2 text-xs'>
                <CopyNumber value={record.sod} label='SOD 号' />
                <p className='mt-1 text-muted-foreground'>写后结果：{record.final_state}</p>
                <p className='mt-1 whitespace-pre-wrap break-words'>{record.reason}</p>
              </div>)}</div>
            </details>
        </li>)}
      </ul>
      {page && !error && page.next_offset < page.total && <div className='flex justify-center py-2'>
        <Button variant='ghost' disabled={busy} onClick={() => setOffset(page.next_offset)}>
          {busy ? '正在加载…' : '加载更多'}
        </Button>
      </div>}
    </div>}
    {busy && <p role='status' className='text-sm text-muted-foreground'>正在读取核销明细…</p>}
    {error && <div role='alert' className='flex items-center gap-2 text-sm text-destructive'>
      {error}<Button variant='outline' onClick={() => setRetry(value => value + 1)}>重试</Button>
    </div>}
    {!busy && !error && page && groups.length === 0 && <p className='text-sm text-muted-foreground'>
      {unavailable.length === page.dates.length ? '暂无可读取的最终明细。' : '已读取日期中没有此类记录。'}
    </p>}
    <p className='text-xs text-muted-foreground'>汇总按记录计数，列表按 AR / SO 合并。</p>
  </section>;
}
