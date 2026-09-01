import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious
} from '@/components/ui/pagination';
import { Progress, ProgressLabel } from '@/components/ui/progress';
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

function stateVariant(state: string): 'secondary' | 'destructive' | 'outline' | 'default' {
  if (state === 'failed') return 'destructive';
  if (state === 'succeeded') return 'default';
  if (state === 'cancelled') return 'outline';
  return 'secondary';
}

function businessDateLabel(item: TaskCenterItem): string {
  if (!item.business_date_start) return '未指定业务日期';
  if (item.business_date_count > 1) {
    return `${item.business_date_count} 个已选核销日`;
  }
  return item.business_date_start;
}

function TaskCenterRow({ item }: { item: TaskCenterItem }) {
  return (
    <article className='grid gap-4 rounded-xl border p-4 md:grid-cols-[minmax(0,1fr)_minmax(12rem,0.7fr)_auto] md:items-center'>
      <div className='min-w-0 space-y-2'>
        <div className='flex flex-wrap items-center gap-2'>
          <Badge variant='outline'>{taskCenterTypeLabel(item.reference_type, item.skill_id)}</Badge>
          <Badge variant={stateVariant(item.view_state)}>
            {taskCenterStateLabel(item.view_state)}
          </Badge>
        </div>
        <div>
          <h3 className='truncate font-medium'>{item.skill_name}</h3>
          {item.business_task_id ? (
            <p className='text-sm text-muted-foreground'>任务号：{item.business_task_id}</p>
          ) : null}
          <p className='text-sm text-muted-foreground'>业务日期：{businessDateLabel(item)}</p>
        </div>
        {item.error_summary ? (
          <p className='text-sm text-destructive'>{item.error_summary}</p>
        ) : null}
      </div>
      <div className='space-y-2'>
        <Progress value={item.progress} aria-label={`${item.skill_name}进度 ${item.progress}%`}>
          <ProgressLabel className='max-w-48 truncate text-xs'>
            {item.progress_message || '等待状态更新'}
          </ProgressLabel>
          <span className='ml-auto text-xs text-muted-foreground tabular-nums'>
            {item.progress}%
          </span>
        </Progress>
        <p className='text-xs text-muted-foreground'>
          更新于{' '}
          {formatDate(item.updated_at, {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
          })}
        </p>
      </div>
      <Link
        href={item.detail_href}
        className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-full md:w-auto')}
      >
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
    ['待处理', data.state_counts.pending, 'border-amber-500/50 bg-amber-500/5'],
    ['执行中', data.state_counts.running, ''],
    ['失败', data.state_counts.failed, 'border-destructive/50 bg-destructive/5'],
    ['已完成', data.state_counts.succeeded, '']
  ] as const;
  const items = data.items ?? [];

  return (
    <div className='space-y-4'>
      <PaginatedCollection
        ariaLabel='任务状态统计'
        contentClassName='grid grid-cols-2 gap-3 lg:grid-cols-4'
      >
        {counts.map(([label, value, className]) => (
          <div key={label} className={cn('rounded-xl border p-4', className)}>
            <p className='text-sm text-muted-foreground'>{label}</p>
            <p className='mt-1 text-2xl font-semibold tabular-nums'>{value}</p>
          </div>
        ))}
      </PaginatedCollection>
      {items.length ? (
        <Card>
          <CardHeader>
            <h2 className='text-base leading-snug font-medium'>正式任务</h2>
            <CardDescription>共 {data.total} 条，按最近更新时间排序。</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            <div
              role='region'
              aria-label='正式任务当前页，每页最多 5 项'
              className='max-h-[36rem] overflow-y-auto overscroll-contain rounded-lg pr-2 [scrollbar-gutter:stable]'
            >
              <div className='space-y-3'>
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
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <h2 className='text-base leading-snug font-medium'>
              {taskCenterEmptyState(hasAnyTasks).title}
            </h2>
            <CardDescription>{taskCenterEmptyState(hasAnyTasks).description}</CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              href={hasAnyTasks ? '/dashboard/runs' : '/dashboard/skills'}
              className={cn(buttonVariants())}
            >
              {taskCenterEmptyState(hasAnyTasks).action}
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
