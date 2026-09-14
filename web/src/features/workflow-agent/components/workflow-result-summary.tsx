'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { WorkflowBatchRead, WorkflowRead } from '@/features/platform-api/types';
import { useId, useState, type JSX, type ReactNode } from 'react';
import { RESULT_COLORS, WorkflowResultDetails, type ResultFilter } from './workflow-result-details';

type ResultSource = Pick<
  WorkflowRead | WorkflowBatchRead,
  'id' | 'updated_at' | 'result_metrics' | 'result_scope' | 'business_items_pending' | 'result_summary'
>;

const FILTERS: Record<string, ResultFilter> = {
  ledger_written: 'written', ledger_final_skipped: 'skipped',
  unallocated_pending: 'hold', conflicts_pending: 'conflict', exceptions: 'exception'
};

const METRICS = [
  ['ledger_to_fill', '待写入'],
  ['ledger_skipped', '已跳过'],
  ['unallocated_pending', '挂账'],
  ['conflicts_pending', '冲突'],
  ['exceptions', '异常']
] as const;

const FINAL_METRICS = [
  ['ledger_written', '已写入'],
  ['ledger_final_skipped', '已跳过'],
  ['unallocated_pending', '挂账'],
  ['conflicts_pending', '冲突'],
  ['exceptions', '异常']
] as const;

const LEGACY_KEYS: Record<string, string> = {
  ledger_to_fill: '今天要填',
  ledger_skipped: '已填过·跳过',
  unallocated_pending: '挂账待办',
  conflicts_pending: '冲突·需你定',
  flow_auto_written: '流转确认后自动写',
  flow_manual_pending: '流转须手填',
  exceptions: '异常'
};

function scopeLabel(scope: string): string {
  if (scope === 'day') return '本日';
  if (scope === 'batch') return '本批次';
  return '范围待核实';
}

function metricValue(
  source: ResultSource,
  key: string,
  final: boolean
): { value: string; meaning: string } {
  const metric = source.result_metrics?.[key];
  if (metric) {
    if (metric.state === 'value' && metric.value !== null && metric.value !== undefined) {
      return { value: String(metric.value), meaning: metric.meaning || '' };
    }
    if (metric.state === 'not_applicable') return { value: '不适用', meaning: metric.meaning || '' };
    if (metric.state === 'read_failed') return { value: '读取失败', meaning: metric.meaning || '' };
    return { value: final ? '尚无完整结果' : '旧版本未记录', meaning: metric.meaning || '' };
  }
  if (final) return { value: '尚无完整结果', meaning: '' };
  const legacy = source.result_summary?.[LEGACY_KEYS[key]];
  if (typeof legacy === 'number' && Number.isFinite(legacy)) {
    return { value: String(legacy), meaning: '兼容旧任务结果' };
  }
  return { value: '旧版本未记录', meaning: '兼容旧任务结果' };
}

export function WorkflowResultSummary({
  source,
  title,
  controls,
  emptyMessage
}: {
  source: ResultSource;
  title: string;
  controls?: ReactNode;
  emptyMessage?: string;
}): JSX.Element | null {
  const [selection, setSelection] = useState<{ sourceId: string; filter: ResultFilter } | null>(null);
  const filter = selection?.sourceId === source.id ? selection.filter : null;
  const detailsId = useId();
  const final = source.result_metrics?.ledger_written !== undefined;
  const definitions = final ? FINAL_METRICS : METRICS;
  const emptyDay = source.result_metrics?.confirmed_empty_day?.value === 1;
  const hasResults = definitions.some(([key]) => {
    const metric = source.result_metrics?.[key];
    return metric?.state === 'read_failed' ||
      (metric?.state === 'value' && typeof metric.value === 'number') ||
      (!final && typeof source.result_summary?.[LEGACY_KEYS[key]] === 'number');
  });
  const noticeCount = (key: string) => {
    const value = source.result_summary?.[key];
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
  };
  const accrualCount = noticeCount('跨月计提SOD数');
  if (!hasResults && !emptyDay && !accrualCount && !emptyMessage) return null;
  const pending = ['unallocated_pending', 'conflicts_pending', 'exceptions'].some(key => {
    const value = source.result_metrics?.[key]?.value ?? source.result_summary?.[LEGACY_KEYS[key]];
    return typeof value === 'number' && value > 0;
  });

  const pendingKnown = emptyDay || ['unallocated_pending', 'conflicts_pending', 'exceptions'].every(key => {
    const metric = source.result_metrics?.[key];
    if (metric) return metric.state === 'value' && typeof metric.value === 'number';
    return !final && typeof source.result_summary?.[LEGACY_KEYS[key]] === 'number';
  });

  const coverage = (key: string) => metricValue(source, key, true).value;
  return (
    <Card>
      <CardHeader className='pb-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <CardTitle className='text-base'>{title}</CardTitle>
          <div className='result-summary-tools'>
            {controls && <div className='result-summary-controls'>{controls}</div>}
            <div className='result-summary-status'>
              <Badge variant='outline' className={pending ? 'border-amber-600/40 text-amber-700 dark:text-amber-300' : pendingKnown ? 'border-emerald-600/30 text-emerald-700 dark:text-emerald-300' : 'text-muted-foreground'}>
                {pending ? '有待处理项' : pendingKnown ? '无待处理项' : '待处理项待核实'}
              </Badge>
              <Badge variant='outline'>{scopeLabel(source.result_scope)}</Badge>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className='space-y-3'>
        {!hasResults && !emptyDay && !accrualCount && <p className='text-sm text-muted-foreground'>{emptyMessage}</p>}
        {emptyDay ? <p className='text-sm text-muted-foreground'>当日无核销记录</p> : hasResults && (
          <div className='grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-5'>
            {definitions.map(([key, label]) => {
              const item = metricValue(source, key, final);
              const expanded = filter === FILTERS[key];
              const colors = RESULT_COLORS[key === 'ledger_skipped' ? 'skipped' : FILTERS[key]];
              const content = <>
                <span className='flex items-center gap-2 text-sm'>{label}{final && <span aria-hidden='true' className='text-xs'>{expanded ? '▴' : '▾'}</span>}</span>
                <span className='mt-1 block text-xl font-semibold tabular-nums break-words'>{item.value}</span>
              </>;
              return <div key={key} className={`min-w-0 ${colors?.text ?? ''}`}>
                {final ? <button type='button' className={`h-full min-h-11 min-w-0 w-full rounded-md border p-2 text-left transition-[filter] hover:brightness-95 dark:hover:brightness-110 focus-visible:outline-2 focus-visible:outline-ring ${colors?.surface ?? ''} ${expanded ? 'ring-1 ring-current' : ''}`}
                  aria-label={`${expanded ? '收起' : '展开'}${label}明细`} aria-expanded={expanded} aria-controls={detailsId} title={item.meaning}
                  onClick={() => setSelection(expanded ? null : { sourceId: source.id, filter: FILTERS[key] })}>{content}</button> : content}
              </div>;
            })}
          </div>
        )}
        {final && source.result_scope === 'batch' && (
          <p className='text-xs text-muted-foreground'>
            已复核 {coverage('result_dates_reviewed')}/{coverage('result_dates_total')} 天
            · 已发布 {coverage('result_dates_published')} 天
            · 无记录 {coverage('result_dates_empty')} 天
            {(source.result_metrics?.result_dates_legacy?.value ?? 0) > 0 &&
              ` · 另有 ${coverage('result_dates_legacy')} 天旧版结果未计入`}
          </p>
        )}
        {accrualCount !== null && accrualCount > 0 && (
          <p role='status' className='text-sm text-amber-700 dark:text-amber-300'>
            跨月计提补填：{source.result_scope === 'batch' ? '已检查日期涉及' : '涉及'} {accrualCount} 项
            · 月份待确认 {noticeCount('跨月计提待确认') ?? '未记录'} 项
            · 冲突 {noticeCount('跨月计提冲突') ?? '未记录'} 项
          </p>
        )}
        <div id={detailsId} hidden={!final || emptyDay || !filter}>
        {final && !emptyDay && filter && <WorkflowResultDetails
          key={`${source.id}:${source.updated_at}:${filter}`} id={source.id} scope={source.result_scope}
          filter={filter} onClose={() => setSelection(null)} />}
        </div>
      </CardContent>
    </Card>
  );
}
