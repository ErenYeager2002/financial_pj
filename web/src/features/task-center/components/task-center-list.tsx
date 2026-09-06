import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious
} from '@/components/ui/pagination';
import { Progress } from '@/components/ui/progress';
import type { TaskCenterItem, TaskCenterPage } from '@/features/platform-api/types';
import {
  taskCenterActionLabel,
  taskCenterEmptyState,
  taskCenterStateLabel,
  taskCenterTypeLabel
} from '@/features/task-center/presentation';
import { taskCenterHref, type TaskCenterQuery } from '@/features/task-center/query';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';

function businessDateLabel(item: TaskCenterItem): string {
  if (!item.business_date_start) return '未指定业务日期';
  if (item.business_date_count > 1) {
    return `${item.business_date_count} 个已选核销日`;
  }
  return item.business_date_start;
}

function TaskCenterRow({ item }: { item: TaskCenterItem }) {
  return (
    <article className='simple-task-row'>
      <div className='min-w-0'>
        <h3 className='font-medium leading-6'>
          <Link href={item.detail_href} className='simple-title-link'>{item.skill_name}</Link>
        </h3>
        <p className='text-xs text-muted-foreground leading-5 break-all'>
          {item.business_task_id || taskCenterTypeLabel(item.reference_type, item.skill_id)}
        </p>
        {item.error_summary ? (
          <details className='simple-task-error'>
            <summary>失败原因</summary>
            <p className='pt-1 text-sm'>{item.error_summary}</p>
            {item.progress_message && item.progress_message !== item.error_summary ? <p className='pt-1 text-xs'>{item.progress_message}</p> : null}
          </details>
        ) : null}
      </div>
      <div className='text-sm tabular-nums'>
        <span className='simple-mobile-label'>业务日期</span>
        {item.business_date_start ? businessDateLabel(item) : '—'}
      </div>
      <div className='min-w-0 space-y-1.5'>
        <span className='simple-task-state' data-state={item.view_state}>
          <span aria-hidden='true' />{taskCenterStateLabel(item.view_state)}
          {item.view_state === 'running' || item.view_state === 'failed' ? ` · ${item.progress}%` : ''}
        </span>
        {item.view_state === 'running' ? (
          <Progress value={item.progress} aria-label={`${item.skill_name}进度 ${item.progress}%`} className='max-w-36' />
        ) : null}
        {item.progress_message && (item.view_state === 'running' || item.view_state === 'pending') ? (
          <p className='text-xs leading-5 text-muted-foreground'>{item.progress_message}</p>
        ) : null}
      </div>
      <div className='text-sm text-muted-foreground tabular-nums'>
        <span className='simple-mobile-label'>更新于</span>
        {formatDate(item.updated_at, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
      </div>
      <Link href={item.detail_href} className='simple-text-action'>
        {taskCenterActionLabel(item.view_state)}
      </Link>
    </article>
  );
}

export function TaskCenterList({
  data,
  query,
  hasAnyTasks
}: {
  data: TaskCenterPage;
  query: TaskCenterQuery;
  hasAnyTasks: boolean;
}) {
  const counts = [
    ['全部', '', null],
    ['待处理', 'pending', data.state_counts.pending],
    ['执行中', 'running', data.state_counts.running],
    ['失败', 'failed', data.state_counts.failed],
    ['已完成', 'succeeded', data.state_counts.succeeded],
    ['已取消', 'cancelled', null]
  ] as const;
  const items = data.items ?? [];
  const hasFilters = Boolean(
    query.query ||
      query.skillId ||
      query.viewState ||
      query.businessDateFrom ||
      query.businessDateTo
  );

  return (
    <div className='space-y-4'>
      <nav className='simple-state-tabs' aria-label='任务状态筛选'>
        {counts.map(([label, state, value]) => (
          <Link key={label} href={taskCenterHref(query, 1, { viewState: state })}
            aria-current={query.viewState === state ? 'page' : undefined}>
            {label}{value !== null ? <span className='tabular-nums'>{value}</span> : null}
          </Link>
        ))}
      </nav>
      <form method='get' className='simple-task-filters'>
        <input type='hidden' name='view_state' value={query.viewState} />
        {query.skillId ? <input type='hidden' name='skill_id' value={query.skillId} /> : null}
        <label className='simple-search'>
          <span className='sr-only'>任务号、名称或 Skill</span>
          <input name='query' defaultValue={query.query} maxLength={128}
            placeholder='搜索任务名称或任务号' />
        </label>
        <button type='submit' className={cn(buttonVariants({ variant: 'outline' }), 'platform-action')}>查询</button>
        <details className='simple-filter-more' open={Boolean(query.businessDateFrom || query.businessDateTo)}>
          <summary>日期与条数{query.businessDateFrom || query.businessDateTo ? ' · 已筛选' : ''}</summary>
          <div className='simple-extra-filters'>
            <label>业务日期起<input type='date' name='business_date_from' defaultValue={query.businessDateFrom} /></label>
            <label>业务日期止<input type='date' name='business_date_to' defaultValue={query.businessDateTo} /></label>
            <label>每页<select name='page_size' defaultValue={String(query.pageSize)}>
              {[10, 25, 50, 100].includes(query.pageSize) ? null : <option value={query.pageSize}>{query.pageSize} 条</option>}
              <option value='10'>10 条</option><option value='25'>25 条</option>
              <option value='50'>50 条</option><option value='100'>100 条</option>
            </select></label>
          </div>
        </details>
        {hasFilters ? <Link href='/dashboard/runs' className='simple-text-action'>清除筛选</Link> : null}
      </form>

      {items.length ? (
        <section className='simple-task-results' aria-label='任务列表'>
          <div className='mb-3 flex flex-wrap items-start justify-between gap-3 text-xs text-muted-foreground'>
            <span>共 {data.total} 条</span>
            {data.scope ? <details className='max-w-md text-right'><summary className='cursor-pointer'>统计范围</summary><p className='py-2'>{data.scope}</p></details> : null}
          </div>
          <div className='space-y-3'>
            <div className='simple-task-head' aria-hidden='true'>
              <span>任务</span><span>业务日期</span><span>状态</span><span>更新时间</span><span>操作</span>
            </div>
            <div
              role='region'
              aria-label={`正式任务当前页，每页 ${data.page_size} 项`}
              className='min-w-0'
            >
              <div className='simple-task-list'>
                {items.map((item) => (
                  <TaskCenterRow key={`${item.reference_type}:${item.reference_id}`} item={item} />
                ))}
              </div>
            </div>
            <Pagination className='pt-2'>
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    href={taskCenterHref(query, Math.max(data.page - 1, 1))}
                    aria-disabled={data.page <= 1}
                    tabIndex={data.page <= 1 ? -1 : undefined}
                    className={data.page <= 1 ? 'pointer-events-none opacity-50' : undefined}
                  />
                </PaginationItem>
                <PaginationItem className='px-3 text-sm text-muted-foreground' aria-live='polite'>
                  第 {data.page} / {data.pages} 页 · 共 {data.total} 项
                </PaginationItem>
                <PaginationItem>
                  <PaginationNext
                    href={taskCenterHref(query, Math.min(data.page + 1, data.pages))}
                    aria-disabled={data.page >= data.pages}
                    tabIndex={data.page >= data.pages ? -1 : undefined}
                    className={
                      data.page >= data.pages ? 'pointer-events-none opacity-50' : undefined
                    }
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          </div>
        </section>
      ) : (
        <Card>
          <CardHeader>
            <h2 className='text-base leading-snug font-medium'>
              {hasFilters ? '当前筛选没有任务' : taskCenterEmptyState(hasAnyTasks).title}
            </h2>
            <CardDescription>
              {hasFilters
                ? '请调整任务号、Skill、状态或业务日期条件。'
                : taskCenterEmptyState(hasAnyTasks).description}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              href={hasFilters ? '/dashboard/runs' : hasAnyTasks ? '/dashboard/runs' : '/dashboard/skills'}
              className={cn(buttonVariants())}
            >
              {hasFilters ? '清除筛选' : taskCenterEmptyState(hasAnyTasks).action}
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
