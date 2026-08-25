'use client';

import * as React from 'react';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import type {
  WorkflowBatchRead,
  WorkflowFetchedData,
  WorkflowRead
} from '@/features/platform-api/types';
import {
  lastPageOffset,
  parseSupplementIdentifiers,
  partitionFetchedArGroups
} from '@/features/workflow-agent/workflow-fetched-data-input';
import { batchFetchedDataWorkflow } from '@/features/workflow-agent/workflow-batch-selection';

interface WorkflowFetchedDataDialogProps {
  workflow?: WorkflowRead;
  batch?: WorkflowBatchRead;
  open: boolean;
  reconciliationDate?: string;
  onOpenChange: (open: boolean) => void;
  onWorkflowChange?: (workflow: WorkflowRead) => void;
  onBatchChange?: (batch: WorkflowBatchRead) => void;
}

const PAGE_SIZE = 50;
type FetchedArGroup = NonNullable<WorkflowFetchedData['ar_groups']>[number];
type FetchedOrderGroup = NonNullable<FetchedArGroup['orders']>[number];
type MoneyValue = { amount: number | null | undefined; currency: string };

function responseMessage(response: Response, fallback: string): Promise<string> {
  return response
    .json()
    .then((body: unknown) => {
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        return body.detail;
      }
      return fallback;
    })
    .catch(() => fallback);
}

function cellValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') return new Intl.NumberFormat('zh-CN').format(value);
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function joinedValues(values: Array<string | null | undefined>): string {
  const unique = [...new Set(values.filter((value): value is string => Boolean(value)))];
  return unique.join('、') || '—';
}

function moneySummary(values: MoneyValue[]): string {
  const totals = new Map<string, number>();
  for (const value of values) {
    if (value.amount === null || value.amount === undefined || !Number.isFinite(value.amount)) {
      continue;
    }
    const currency = value.currency || '币种未提供';
    totals.set(currency, (totals.get(currency) ?? 0) + value.amount);
  }
  if (!totals.size) return '—';
  return [...totals.entries()]
    .map(([currency, amount]) => `${cellValue(amount)} ${currency}`)
    .join(' + ');
}

function originalOrLocalMoney(
  amountOriginal: number | null | undefined,
  amountLocal: number | null | undefined,
  currency: string
): MoneyValue {
  return {
    amount: amountOriginal ?? amountLocal,
    currency: amountOriginal !== null && amountOriginal !== undefined ? currency : 'CNY'
  };
}

function writeoffMoney(order: FetchedOrderGroup): MoneyValue[] {
  return (order.writeoffs ?? []).map((item) =>
    originalOrLocalMoney(item.amount_original, item.amount_local, item.currency)
  );
}

function toggleExpanded(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

function firstSummaryValue(summary: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = summary[key];
    if (value !== undefined && value !== null && value !== '') return cellValue(value);
  }
  return '未提供';
}

function isEmptyFetchedSummary(summary: Record<string, unknown>): boolean {
  const keys = ['回款记录笔数', '下单行数', '核销明细行数', '订单明细SOD行数'];
  return keys.every((key) => summary[key] === 0);
}

function supplementCount(item: Record<string, unknown>, group: string): string {
  const value = item[group];
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '0';
  const groups = value as Record<string, unknown>;
  const ar = Array.isArray(groups.ar_ids) ? groups.ar_ids.length : 0;
  const so = Array.isArray(groups.so_ids) ? groups.so_ids.length : 0;
  return `AR ${ar} 个，SO ${so} 个`;
}

export function WorkflowFetchedDataDialog({
  workflow,
  batch,
  open,
  reconciliationDate: requestedReconciliationDate,
  onOpenChange,
  onWorkflowChange,
  onBatchChange
}: WorkflowFetchedDataDialogProps): React.JSX.Element {
  if (!workflow && !batch) throw new Error('取数检查缺少任务或批次。');
  const [offset, setOffset] = React.useState(0);
  const [queryInput, setQueryInput] = React.useState('');
  const [query, setQuery] = React.useState('');
  const [issuesOnly, setIssuesOnly] = React.useState(false);
  const [expandedArIds, setExpandedArIds] = React.useState<Set<string>>(new Set());
  const [expandedSoIds, setExpandedSoIds] = React.useState<Set<string>>(new Set());
  const [reconciliationDate, setReconciliationDate] = React.useState(
    requestedReconciliationDate ??
      workflow?.reconciliation_date ??
      batch?.reconciliation_dates[0] ??
      ''
  );
  const [preview, setPreview] = React.useState<WorkflowFetchedData | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [loadError, setLoadError] = React.useState('');
  const [actionError, setActionError] = React.useState('');
  const [arInput, setArInput] = React.useState('');
  const [soInput, setSoInput] = React.useState('');
  const [showSupplementForm, setShowSupplementForm] = React.useState(false);
  const [submitting, setSubmitting] = React.useState('');
  const resourceId = batch?.id ?? workflow?.id ?? '';
  const resourceUpdatedAt = batch?.updated_at ?? workflow?.updated_at ?? '';
  const stage = batch
    ? (batchFetchedDataWorkflow(batch.workflows)?.stage ?? '')
    : (workflow?.stage ?? '');
  const supplementHistory = batch
    ? batch.fetched_data_supplement_history
    : workflow?.fetched_data_supplement_history;

  React.useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    async function loadPreview() {
      setLoading(true);
      setLoadError('');
      try {
        const search = new URLSearchParams({
          dataset: 'ar_groups',
          offset: String(offset),
          limit: String(PAGE_SIZE)
        });
        if (query.trim()) search.set('query', query.trim());
        if (issuesOnly) search.set('issues_only', 'true');
        if (batch) search.set('reconciliation_date', reconciliationDate);
        const response = await fetch(
          batch
            ? `/api/platform/workflow-batches/${encodeURIComponent(resourceId)}/fetched-data?${search.toString()}`
            : `/api/platform/workflows/${encodeURIComponent(resourceId)}/fetched-data?${search.toString()}`,
          { cache: 'no-store', signal: controller.signal }
        );
        if (!response.ok)
          throw new Error(await responseMessage(response, '智云取数数据加载失败。'));
        setPreview((await response.json()) as WorkflowFetchedData);
      } catch (loadError) {
        if (loadError instanceof DOMException && loadError.name === 'AbortError') return;
        setLoadError(loadError instanceof Error ? loadError.message : '智云取数数据加载失败。');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void loadPreview();
    return () => controller.abort();
  }, [batch, issuesOnly, offset, open, query, reconciliationDate, resourceId, resourceUpdatedAt]);

  React.useEffect(() => {
    if (!open) setShowSupplementForm(false);
  }, [open]);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(queryInput);
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [queryInput]);

  React.useEffect(() => {
    if (open && requestedReconciliationDate) setReconciliationDate(requestedReconciliationDate);
  }, [open, requestedReconciliationDate]);

  React.useEffect(() => {
    if (!preview?.ar_groups) return;
    setExpandedArIds((current) => {
      const next = new Set(current);
      for (const group of preview.ar_groups ?? []) {
        if ((group.issues?.length ?? 0) > 0) next.add(group.ar_id);
      }
      return next;
    });
  }, [preview]);

  async function submitReview(action: 'confirm' | 'supplement') {
    if (submitting) return;
    const arIds = parsedAr.values;
    const soIds = parsedSo.values;
    const invalidIds = [...parsedAr.invalid, ...parsedSo.invalid];
    if (action === 'supplement' && invalidIds.length) {
      setActionError(`编号格式无效：${invalidIds.slice(0, 5).join('、')}`);
      return;
    }
    if (action === 'supplement' && !arIds.length && !soIds.length) {
      setActionError('请至少填写一个缺失的 AR 或 SO 编号。');
      return;
    }
    setSubmitting(action);
    setActionError('');
    try {
      const response = await fetch(
        batch
          ? `/api/platform/workflow-batches/${encodeURIComponent(resourceId)}/fetched-data/${action}`
          : `/api/platform/workflows/${encodeURIComponent(resourceId)}/fetched-data/${action}`,
        action === 'supplement'
          ? {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                ar_ids: arIds,
                so_ids: soIds,
                ...(batch ? { reconciliation_date: reconciliationDate } : {})
              })
            }
          : { method: 'POST' }
      );
      if (!response.ok)
        throw new Error(
          await responseMessage(response, action === 'confirm' ? '确认失败。' : '补取失败。')
        );
      const updated = (await response.json()) as WorkflowRead | WorkflowBatchRead;
      if (batch) onBatchChange?.(updated as WorkflowBatchRead);
      else onWorkflowChange?.(updated as WorkflowRead);
      if (action === 'confirm') onOpenChange(false);
      else {
        setArInput('');
        setSoInput('');
        setShowSupplementForm(false);
      }
    } catch (submitError) {
      setActionError(submitError instanceof Error ? submitError.message : '操作失败。');
    } finally {
      setSubmitting('');
    }
  }

  const parsedAr = React.useMemo(() => parseSupplementIdentifiers(arInput, 'AR'), [arInput]);
  const parsedSo = React.useMemo(() => parseSupplementIdentifiers(soInput, 'SO'), [soInput]);
  const hasSupplementIds = parsedAr.values.length > 0 || parsedSo.values.length > 0;
  const hasInvalidSupplementIds = parsedAr.invalid.length > 0 || parsedSo.invalid.length > 0;
  const lastOffset = preview ? lastPageOffset(preview.total, PAGE_SIZE) : 0;
  const start = preview?.total ? preview.offset + 1 : 0;
  const end = preview
    ? Math.min(preview.offset + (preview.ar_groups?.length ?? 0), preview.total)
    : 0;
  const summary = preview?.summary ?? {};
  const partitionedArGroups = partitionFetchedArGroups(preview?.ar_groups);
  const displayedArGroups = [
    ...partitionedArGroups.current.map((group) => ({ group, historicalReference: false })),
    ...partitionedArGroups.historicalReferences.map((group) => ({
      group,
      historicalReference: true
    }))
  ];
  const businessSummary = [
    { label: '回款记录', keys: ['回款记录笔数'] },
    { label: '关联订单行数', keys: ['下单行数'] },
    { label: '核销明细', keys: ['核销明细行数'] },
    { label: '订单明细 SOD', keys: ['订单明细SOD行数'] },
    { label: 'AR 覆盖', keys: ['AR覆盖率', 'AR覆盖'] },
    { label: 'AR/SO 覆盖', keys: ['AR/SO覆盖率', 'AR/SO覆盖'] },
    {
      label: '异常',
      keys: ['异常数量'],
      format: (value: Record<string, unknown>) => {
        const items = [
          ['无订单 AR', '无下单行的AR数量'],
          ['无 SOD SO', '查不到SOD的SO数量'],
          ['缺交付日期 SO', '缺项目交付日期的SO数量']
        ]
          .filter(([, key]) => value[key] !== undefined)
          .map(([label, key]) => `${label} ${cellValue(value[key])}`);
        return items.length ? items.join('；') : firstSummaryValue(value, ['异常数量']);
      }
    }
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='flex max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-6xl'>
        <DialogHeader className='border-b px-5 py-4 pr-12'>
          <DialogTitle>智云取数数据</DialogTitle>
          <DialogDescription>
            核销日期：{reconciliationDate}
            。请检查本次已拉取的数据；只有明确确认后才会继续核销判定。
          </DialogDescription>
          {batch && batch.reconciliation_dates.length > 1 && (
            <label className='mt-2 flex items-center gap-2 text-sm'>
              <span>查看日期</span>
              <select
                className='rounded-md border bg-background px-2 py-1'
                value={reconciliationDate}
                onChange={(event) => {
                  setReconciliationDate(event.target.value);
                  setPreview(null);
                  setOffset(0);
                  setExpandedArIds(new Set());
                  setExpandedSoIds(new Set());
                }}
              >
                {batch.reconciliation_dates.map((date) => (
                  <option key={date} value={date}>
                    {date}
                  </option>
                ))}
              </select>
            </label>
          )}
        </DialogHeader>

        <div
          data-testid='fetched-data-scroll-region'
          className='min-h-0 flex-1 overflow-y-auto px-5 py-4'
        >
          {preview && (
            <dl className='mb-4 grid gap-2 rounded-lg border bg-muted/30 p-3 text-sm sm:grid-cols-2 lg:grid-cols-4'>
              {businessSummary.map((item) => (
                <div key={item.label} className='min-w-0'>
                  <dt className='text-muted-foreground'>{item.label}</dt>
                  <dd className='mt-0.5 break-words font-medium'>
                    {'format' in item && item.format
                      ? item.format(summary)
                      : firstSummaryValue(summary, item.keys)}
                  </dd>
                </div>
              ))}
            </dl>
          )}

          {preview && isEmptyFetchedSummary(summary) && (
            <Alert className='mb-4'>
              <AlertTitle>本日没有核销记录</AlertTitle>
              <AlertDescription>
                {batch
                  ? '确认后将标记本日已完成并跳过，不执行核销判定和写入，批次继续执行下一天。'
                  : '确认后将标记本日已完成并跳过，不执行核销判定和写入。'}
              </AlertDescription>
            </Alert>
          )}

          {loadError ? (
            <Alert variant='destructive'>
              <AlertTitle>无法显示取数数据</AlertTitle>
              <AlertDescription>{loadError}</AlertDescription>
            </Alert>
          ) : loading && !preview ? (
            <p className='py-12 text-center text-sm text-muted-foreground'>正在读取取数数据…</p>
          ) : preview ? (
            <>
              <div className='mb-3 flex flex-wrap items-end justify-between gap-3'>
                <div>
                  <p className='font-medium'>按 AR 分组</p>
                  <p className='text-sm text-muted-foreground'>
                    当前页：本日 {partitionedArGroups.current.length} 个 AR
                    {partitionedArGroups.historicalReferences.length > 0
                      ? `，历史累计参考 ${partitionedArGroups.historicalReferences.length} 个`
                      : ''}
                    （总记录第 {start}–{end} 个）
                  </p>
                </div>
                <div className='flex flex-wrap items-center gap-3'>
                  <label className='space-y-1 text-xs text-muted-foreground'>
                    <span className='block'>搜索 AR、SO、SOD 或客户</span>
                    <input
                      type='search'
                      className='h-9 w-64 rounded-md border bg-background px-3 text-sm text-foreground'
                      value={queryInput}
                      onChange={(event) => setQueryInput(event.target.value)}
                      placeholder='输入编号或客户名称'
                    />
                  </label>
                  <label className='flex h-9 items-center gap-2 text-sm'>
                    <input
                      type='checkbox'
                      checked={issuesOnly}
                      onChange={(event) => {
                        setIssuesOnly(event.target.checked);
                        setOffset(0);
                        setPreview(null);
                      }}
                    />
                    只看异常
                  </label>
                </div>
              </div>
              <div
                data-testid='ar-group-table-scroll'
                className='max-h-[48dvh] overflow-auto rounded-lg border [&_[data-slot=table-container]]:overflow-visible'
              >
                <Table>
                  <TableHeader className='bg-muted'>
                    <TableRow>
                      <TableHead className='sticky top-0 z-20 min-w-40 bg-muted shadow-[inset_0_-1px_0_var(--border)]'>
                        AR 编号
                      </TableHead>
                      <TableHead className='sticky top-0 z-20 min-w-40 bg-muted shadow-[inset_0_-1px_0_var(--border)]'>
                        客户
                      </TableHead>
                      <TableHead className='sticky top-0 z-20 min-w-28 bg-muted shadow-[inset_0_-1px_0_var(--border)]'>
                        到账日期
                      </TableHead>
                      <TableHead className='sticky top-0 z-20 bg-muted text-right shadow-[inset_0_-1px_0_var(--border)]'>
                        回款金额
                      </TableHead>
                      <TableHead className='sticky top-0 z-20 bg-muted shadow-[inset_0_-1px_0_var(--border)]'>
                        币种
                      </TableHead>
                      <TableHead className='sticky top-0 z-20 bg-muted text-right shadow-[inset_0_-1px_0_var(--border)]'>
                        关联 SO
                      </TableHead>
                      <TableHead className='sticky top-0 z-20 min-w-28 bg-muted shadow-[inset_0_-1px_0_var(--border)]'>
                        核销状态
                      </TableHead>
                      <TableHead className='sticky top-0 z-20 min-w-36 bg-muted shadow-[inset_0_-1px_0_var(--border)]'>
                        数据情况
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {displayedArGroups.length > 0 ? (
                      displayedArGroups.map(({ group, historicalReference }, groupIndex) => {
                        const payments = group.payments ?? [];
                        const orders = group.orders ?? [];
                        const expanded = expandedArIds.has(group.ar_id);
                        const paymentTotal = moneySummary(
                          payments.map((payment) =>
                            originalOrLocalMoney(
                              payment.amount_original,
                              payment.amount_local,
                              payment.currency
                            )
                          )
                        );
                        return (
                          <React.Fragment key={group.ar_id}>
                            {historicalReference &&
                              groupIndex === partitionedArGroups.current.length && (
                                <TableRow className='border-y bg-amber-50/80 hover:bg-amber-50/80 dark:bg-amber-950/20 dark:hover:bg-amber-950/20'>
                                  <TableCell colSpan={8} className='py-3'>
                                    <p className='font-medium text-amber-900 dark:text-amber-200'>
                                      历史累计参考
                                    </p>
                                    <p className='mt-0.5 text-xs font-normal text-amber-800/80 dark:text-amber-300/80'>
                                      以下记录仅用于核对同一 SO 的累计核销，不属于本日处理对象。
                                    </p>
                                  </TableCell>
                                </TableRow>
                              )}
                            <TableRow
                              className={
                                historicalReference
                                  ? 'bg-amber-50/40 font-medium dark:bg-amber-950/10'
                                  : 'bg-muted/20 font-medium'
                              }
                            >
                              <TableCell>
                                <button
                                  type='button'
                                  className='flex items-center gap-2 text-left hover:underline'
                                  aria-expanded={expanded}
                                  onClick={() =>
                                    setExpandedArIds((current) =>
                                      toggleExpanded(current, group.ar_id)
                                    )
                                  }
                                >
                                  {expanded ? (
                                    <Icons.chevronDown className='size-4 shrink-0' />
                                  ) : (
                                    <Icons.chevronRight className='size-4 shrink-0' />
                                  )}
                                  {group.ar_id}
                                </button>
                                <span className='ml-6 block text-xs font-normal text-muted-foreground'>
                                  {historicalReference ? '历史累计参考 · ' : ''}
                                  {orders.length} 个 SO
                                  {payments.length > 1 ? ` · ${payments.length} 条回款记录` : ''}
                                </span>
                              </TableCell>
                              <TableCell>
                                {joinedValues(payments.map((item) => item.customer))}
                              </TableCell>
                              <TableCell>
                                {joinedValues(
                                  payments.map(
                                    (item) => item.arrival_date || item.reconciliation_date
                                  )
                                )}
                              </TableCell>
                              <TableCell className='text-right tabular-nums'>
                                {paymentTotal}
                              </TableCell>
                              <TableCell>
                                {joinedValues(payments.map((item) => item.currency))}
                              </TableCell>
                              <TableCell className='text-right tabular-nums'>
                                {orders.length}
                              </TableCell>
                              <TableCell>
                                {joinedValues(payments.map((item) => item.writeoff_status))}
                              </TableCell>
                              <TableCell>
                                {(group.issues?.length ?? 0) > 0 ? (
                                  <span className='text-destructive'>
                                    待检查（{group.issues?.length}）
                                  </span>
                                ) : (
                                  <span className='text-emerald-700 dark:text-emerald-400'>
                                    数据完整
                                  </span>
                                )}
                              </TableCell>
                            </TableRow>
                            {expanded && orders.length > 0 && (
                              <TableRow className='bg-muted/10 hover:bg-muted/10'>
                                <TableCell colSpan={8} className='p-3 pl-8'>
                                  <section aria-label={`${group.ar_id} 关联 SO`}>
                                    <h4 className='mb-2 text-xs font-medium text-muted-foreground'>
                                      关联 SO
                                    </h4>
                                    <div className='overflow-hidden rounded-md border bg-background'>
                                      <table className='w-full min-w-[900px] text-sm'>
                                        <thead className='bg-muted/60 text-foreground'>
                                          <tr className='border-b'>
                                            <th className='h-9 px-3 text-left font-medium'>
                                              SO 编号
                                            </th>
                                            <th className='h-9 px-3 text-left font-medium'>
                                              订单名称
                                            </th>
                                            <th className='h-9 px-3 text-left font-medium'>
                                              交付日期
                                            </th>
                                            <th className='h-9 px-3 text-right font-medium'>
                                              交付金额
                                            </th>
                                            <th className='h-9 px-3 text-right font-medium'>
                                              已核销金额
                                            </th>
                                            <th className='h-9 px-3 text-left font-medium'>币种</th>
                                            <th className='h-9 px-3 text-right font-medium'>
                                              SOD 数量
                                            </th>
                                            <th className='h-9 px-3 text-left font-medium'>
                                              数据情况
                                            </th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {orders.map((order) => {
                                            const deliveries = order.deliveries ?? [];
                                            const orderKey = `${group.ar_id}/${order.so_id}`;
                                            const orderExpanded = expandedSoIds.has(orderKey);
                                            return (
                                              <React.Fragment key={orderKey}>
                                                <tr className='border-b transition-colors hover:bg-muted/30'>
                                                  <td className='px-3 py-2 align-middle'>
                                                    <button
                                                      type='button'
                                                      className='flex min-h-8 items-center gap-2 text-left font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
                                                      aria-expanded={orderExpanded}
                                                      onClick={() =>
                                                        setExpandedSoIds((current) =>
                                                          toggleExpanded(current, orderKey)
                                                        )
                                                      }
                                                    >
                                                      {orderExpanded ? (
                                                        <Icons.chevronDown className='size-4 shrink-0' />
                                                      ) : (
                                                        <Icons.chevronRight className='size-4 shrink-0' />
                                                      )}
                                                      {order.so_id}
                                                    </button>
                                                    <span className='ml-6 block text-xs text-muted-foreground'>
                                                      {order.writeoffs?.length ?? 0} 笔核销明细
                                                    </span>
                                                  </td>
                                                  <td className='px-3 py-2 align-middle'>
                                                    {joinedValues(
                                                      deliveries.map((item) => item.order_name)
                                                    )}
                                                  </td>
                                                  <td className='px-3 py-2 align-middle'>
                                                    {joinedValues(
                                                      deliveries.map((item) => item.delivery_date)
                                                    )}
                                                  </td>
                                                  <td className='px-3 py-2 text-right align-middle tabular-nums'>
                                                    {moneySummary(
                                                      deliveries.map((item) => ({
                                                        amount: item.delivery_amount_original,
                                                        currency: item.currency
                                                      }))
                                                    )}
                                                  </td>
                                                  <td className='px-3 py-2 text-right align-middle tabular-nums'>
                                                    {moneySummary(writeoffMoney(order))}
                                                  </td>
                                                  <td className='px-3 py-2 align-middle'>
                                                    {joinedValues([
                                                      ...deliveries.map((item) => item.currency),
                                                      ...(order.writeoffs ?? []).map(
                                                        (item) => item.currency
                                                      )
                                                    ])}
                                                  </td>
                                                  <td className='px-3 py-2 text-right align-middle tabular-nums'>
                                                    {order.order_details?.length ?? 0}
                                                  </td>
                                                  <td className='px-3 py-2 align-middle'>
                                                    {(order.issues?.length ?? 0) > 0 ? (
                                                      <span
                                                        className='text-destructive'
                                                        title={order.issues?.join('；')}
                                                      >
                                                        {order.issues?.join('；')}
                                                      </span>
                                                    ) : (
                                                      '数据完整'
                                                    )}
                                                  </td>
                                                </tr>
                                                {orderExpanded && (
                                                  <tr className='border-b bg-muted/20'>
                                                    <td colSpan={8} className='p-3 pl-8'>
                                                      <div className='space-y-3'>
                                                        <section
                                                          aria-label={`${order.so_id} 核销明细`}
                                                        >
                                                          <h5 className='mb-2 text-xs font-medium text-muted-foreground'>
                                                            核销明细
                                                          </h5>
                                                          <div className='overflow-hidden rounded-md border bg-background'>
                                                            <table className='w-full min-w-[680px] text-sm'>
                                                              <thead className='bg-muted/50'>
                                                                <tr className='border-b'>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    核销记录
                                                                  </th>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    核销日期
                                                                  </th>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    订单名称
                                                                  </th>
                                                                  <th className='h-9 px-3 text-right font-medium'>
                                                                    核销金额
                                                                  </th>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    币种
                                                                  </th>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    状态
                                                                  </th>
                                                                </tr>
                                                              </thead>
                                                              <tbody>
                                                                {(order.writeoffs?.length ?? 0) >
                                                                0 ? (
                                                                  order.writeoffs?.map(
                                                                    (item, index) => (
                                                                      <tr
                                                                        key={`${orderKey}/writeoff/${item.writeoff_id}/${index}`}
                                                                        className='border-b last:border-0'
                                                                      >
                                                                        <td className='px-3 py-2'>
                                                                          {cellValue(
                                                                            item.writeoff_id
                                                                          )}
                                                                        </td>
                                                                        <td className='px-3 py-2'>
                                                                          {cellValue(
                                                                            item.reconciliation_date
                                                                          )}
                                                                        </td>
                                                                        <td className='px-3 py-2'>
                                                                          {cellValue(
                                                                            item.order_name
                                                                          )}
                                                                        </td>
                                                                        <td className='px-3 py-2 text-right tabular-nums'>
                                                                          {moneySummary([
                                                                            originalOrLocalMoney(
                                                                              item.amount_original,
                                                                              item.amount_local,
                                                                              item.currency
                                                                            )
                                                                          ])}
                                                                        </td>
                                                                        <td className='px-3 py-2'>
                                                                          {cellValue(item.currency)}
                                                                        </td>
                                                                        <td className='px-3 py-2'>
                                                                          {item.revoked
                                                                            ? '已撤销'
                                                                            : '有效'}
                                                                        </td>
                                                                      </tr>
                                                                    )
                                                                  )
                                                                ) : (
                                                                  <tr>
                                                                    <td
                                                                      colSpan={6}
                                                                      className='px-3 py-4 text-center text-muted-foreground'
                                                                    >
                                                                      没有核销明细
                                                                    </td>
                                                                  </tr>
                                                                )}
                                                              </tbody>
                                                            </table>
                                                          </div>
                                                        </section>

                                                        <section
                                                          aria-label={`${order.so_id} SOD 明细`}
                                                        >
                                                          <h5 className='mb-2 text-xs font-medium text-muted-foreground'>
                                                            SOD 明细
                                                          </h5>
                                                          <div className='overflow-hidden rounded-md border bg-background'>
                                                            <table className='w-full min-w-[520px] text-sm'>
                                                              <thead className='bg-muted/50'>
                                                                <tr className='border-b'>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    SOD 编号
                                                                  </th>
                                                                  <th className='h-9 px-3 text-right font-medium'>
                                                                    交付金额
                                                                  </th>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    币种
                                                                  </th>
                                                                  <th className='h-9 px-3 text-left font-medium'>
                                                                    项目状态
                                                                  </th>
                                                                </tr>
                                                              </thead>
                                                              <tbody>
                                                                {(order.order_details?.length ??
                                                                  0) > 0 ? (
                                                                  order.order_details?.map(
                                                                    (item, index) => (
                                                                      <tr
                                                                        key={`${orderKey}/sod/${item.sod_id}/${index}`}
                                                                        className='border-b last:border-0'
                                                                      >
                                                                        <td className='px-3 py-2'>
                                                                          {cellValue(item.sod_id)}
                                                                        </td>
                                                                        <td className='px-3 py-2 text-right tabular-nums'>
                                                                          {moneySummary([
                                                                            {
                                                                              amount:
                                                                                item.delivery_amount_original,
                                                                              currency:
                                                                                item.currency
                                                                            }
                                                                          ])}
                                                                        </td>
                                                                        <td className='px-3 py-2'>
                                                                          {cellValue(item.currency)}
                                                                        </td>
                                                                        <td className='px-3 py-2'>
                                                                          {cellValue(
                                                                            item.project_status
                                                                          )}
                                                                        </td>
                                                                      </tr>
                                                                    )
                                                                  )
                                                                ) : (
                                                                  <tr>
                                                                    <td
                                                                      colSpan={4}
                                                                      className='px-3 py-4 text-center text-destructive'
                                                                    >
                                                                      未找到
                                                                      SOD，可使用下方“发现缺失数据”补取。
                                                                    </td>
                                                                  </tr>
                                                                )}
                                                              </tbody>
                                                            </table>
                                                          </div>
                                                        </section>
                                                      </div>
                                                    </td>
                                                  </tr>
                                                )}
                                              </React.Fragment>
                                            );
                                          })}
                                        </tbody>
                                      </table>
                                    </div>
                                  </section>
                                </TableCell>
                              </TableRow>
                            )}
                            {expanded && orders.length === 0 && (
                              <TableRow>
                                <TableCell colSpan={8} className='pl-14 text-destructive'>
                                  当前 AR 没有关联订单，可使用下方“发现缺失数据”补取。
                                </TableCell>
                              </TableRow>
                            )}
                          </React.Fragment>
                        );
                      })
                    ) : (
                      <TableRow>
                        <TableCell colSpan={8} className='h-24 text-center text-muted-foreground'>
                          {queryInput || issuesOnly
                            ? '没有符合当前筛选条件的 AR'
                            : '当天没有核销记录，可以继续'}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
              <div className='mt-3 flex justify-end gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={loading || offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  上一页
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={loading || !(preview.ar_groups?.length ?? 0) || offset >= lastOffset}
                  onClick={() => setOffset(Math.min(lastOffset, offset + PAGE_SIZE))}
                >
                  下一页
                </Button>
              </div>
            </>
          ) : (
            <p className='py-12 text-center text-sm text-muted-foreground'>正在准备取数数据…</p>
          )}
        </div>

        {stage === 'awaiting_fetched_data_confirmation' && (
          <section
            data-testid='fetched-data-review-actions'
            className='max-h-[42dvh] shrink-0 overflow-y-auto border-t bg-background px-5 py-3'
          >
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <div className='min-w-0'>
                <h3 className='font-medium'>工作人员检查</h3>
                <p className='text-sm text-muted-foreground'>
                  确认数据完整后继续；发现缺失数据时可按 AR/SO 编号补取。
                </p>
              </div>
              <div className='flex flex-wrap gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  disabled={Boolean(submitting)}
                  aria-expanded={showSupplementForm}
                  onClick={() => setShowSupplementForm((current) => !current)}
                >
                  发现缺失数据
                </Button>
                <Button
                  type='button'
                  disabled={Boolean(submitting)}
                  onClick={() => void submitReview('confirm')}
                >
                  {submitting === 'confirm' ? '正在继续…' : '数据完整，继续处理'}
                </Button>
              </div>
            </div>

            {showSupplementForm && (
              <div className='mt-3 space-y-3 rounded-lg border bg-muted/20 p-3'>
                <p className='text-sm text-muted-foreground'>
                  可填写多个完整编号，用空格、换行、逗号或分号分隔。补取完成后任务会再次暂停供你确认。
                </p>
                <div className='grid gap-3 sm:grid-cols-2'>
                  <label className='space-y-1 text-sm'>
                    <span>缺失 AR 编号</span>
                    <textarea
                      className='min-h-20 w-full rounded-md border bg-background p-2'
                      value={arInput}
                      onChange={(event) => setArInput(event.target.value)}
                      placeholder='例如：AR26070140；可填写多个'
                    />
                    {parsedAr.invalid.length > 0 && (
                      <span className='block text-destructive'>
                        格式无效：{parsedAr.invalid.slice(0, 5).join('、')}
                      </span>
                    )}
                  </label>
                  <label className='space-y-1 text-sm'>
                    <span>缺失 SO 编号</span>
                    <textarea
                      className='min-h-20 w-full rounded-md border bg-background p-2'
                      value={soInput}
                      onChange={(event) => setSoInput(event.target.value)}
                      placeholder='例如：SO26020320；可填写多个'
                    />
                    {parsedSo.invalid.length > 0 && (
                      <span className='block text-destructive'>
                        格式无效：{parsedSo.invalid.slice(0, 5).join('、')}
                      </span>
                    )}
                  </label>
                </div>
                <div className='flex justify-end'>
                  <Button
                    type='button'
                    variant='outline'
                    disabled={Boolean(submitting) || !hasSupplementIds || hasInvalidSupplementIds}
                    onClick={() => void submitReview('supplement')}
                  >
                    {submitting === 'supplement' ? '正在补取…' : '按编号补取'}
                  </Button>
                </div>
                {(supplementHistory?.length ?? 0) > 0 && (
                  <div className='rounded-md bg-muted/40 p-3 text-sm'>
                    <p className='font-medium'>补取记录</p>
                    <ul className='mt-2 space-y-2 text-xs'>
                      {supplementHistory?.map((item, index) => (
                        <li
                          key={`${String(item.completed_at ?? '')}-${index}`}
                          className='rounded border bg-background p-2'
                        >
                          <p className='font-medium'>
                            {typeof item.completed_at === 'string'
                              ? new Date(item.completed_at).toLocaleString('zh-CN')
                              : '时间未提供'}
                          </p>
                          <p className='mt-1 text-muted-foreground'>
                            请求：{supplementCount(item, 'requested')}；找到：
                            {supplementCount(item, 'found')}；新增：
                            {supplementCount(item, 'added')}；未解决：
                            {supplementCount(item, 'unresolved')}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {actionError && (
              <p role='alert' className='mt-3 text-sm text-destructive'>
                {actionError}
              </p>
            )}
          </section>
        )}
        {stage === 'supplementing_fetched_data' && (
          <div className='shrink-0 border-t bg-muted/30 px-5 py-3 text-sm'>
            正在按编号补取数据。完成后这里会恢复确认操作，请重新检查补取结果。
          </div>
        )}
        <DialogFooter className='shrink-0' showCloseButton />
      </DialogContent>
    </Dialog>
  );
}
