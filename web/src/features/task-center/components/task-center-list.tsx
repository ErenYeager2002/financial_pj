import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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
import {
  hasTaskCenterFilters,
  taskCenterHref,
  type TaskCenterQuery
} from '@/features/task-center/query';
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
    return `${item.business_date_start} 至 ${item.business_date_end} · ${item.business_date_count} 天`;
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

function TaskCenterFilters({ query }: { query: TaskCenterQuery }) {
  return (
    <form action='/dashboard/runs' className='grid gap-3 rounded-xl border p-4 lg:grid-cols-4'>
      <label className='grid gap-1 text-sm'>
        <span className='text-muted-foreground'>状态</span>
        <select
          name='state'
          defaultValue={query.state}
          className='h-9 rounded-md border bg-background px-3'
        >
          <option value=''>全部状态</option>
          <option value='pending'>待处理</option>
          <option value='running'>执行中</option>
          <option value='failed'>失败</option>
          <option value='succeeded'>已完成</option>
          <option value='cancelled'>已取消</option>
        </select>
      </label>
      <label className='grid gap-1 text-sm'>
        <span className='text-muted-foreground'>任务类型</span>
        <select
          name='type'
          defaultValue={query.type}
          className='h-9 rounded-md border bg-background px-3'
        >
          <option value=''>全部类型</option>
          <option value='run'>普通任务</option>
          <option value='workflow'>日期任务</option>
          <option value='workflow_batch'>批次任务</option>
        </select>
      </label>
      <label htmlFor='task-center-skill' className='grid gap-1 text-sm lg:col-span-2'>
        <span className='text-muted-foreground'>Skill</span>
        <Input
          id='task-center-skill'
          name='skill'
          defaultValue={query.skill}
          placeholder='输入 Skill 标识'
        />
      </label>
      <label htmlFor='task-center-business-from' className='grid gap-1 text-sm'>
        <span className='text-muted-foreground'>业务日期从</span>
        <Input
          id='task-center-business-from'
          name='business_from'
          type='date'
          defaultValue={query.businessFrom}
        />
      </label>
      <label htmlFor='task-center-business-to' className='grid gap-1 text-sm'>
        <span className='text-muted-foreground'>业务日期到</span>
        <Input
          id='task-center-business-to'
          name='business_to'
          type='date'
          defaultValue={query.businessTo}
        />
      </label>
      <label htmlFor='task-center-updated-from' className='grid gap-1 text-sm'>
        <span className='text-muted-foreground'>更新时间从</span>
        <Input
          id='task-center-updated-from'
          name='updated_from'
          type='datetime-local'
          defaultValue={query.updatedFrom}
        />
      </label>
      <label htmlFor='task-center-updated-to' className='grid gap-1 text-sm'>
        <span className='text-muted-foreground'>更新时间到</span>
        <Input
          id='task-center-updated-to'
          name='updated_to'
          type='datetime-local'
          defaultValue={query.updatedTo}
        />
      </label>
      <div className='flex flex-wrap gap-2 lg:col-span-4'>
        <button type='submit' className={cn(buttonVariants({ size: 'sm' }))}>
          应用筛选
        </button>
        {hasTaskCenterFilters(query) ? (
          <Link
            href='/dashboard/runs'
            className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
          >
            清除筛选
          </Link>
        ) : null}
      </div>
    </form>
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
  const filtersActive = hasTaskCenterFilters(query);
  const items = data.items ?? [];

  return (
    <div className='space-y-4'>
      <div className='grid grid-cols-2 gap-3 lg:grid-cols-4' aria-label='任务状态统计'>
        {counts.map(([label, value, className]) => (
          <div key={label} className={cn('rounded-xl border p-4', className)}>
            <p className='text-sm text-muted-foreground'>{label}</p>
            <p className='mt-1 text-2xl font-semibold tabular-nums'>{value}</p>
          </div>
        ))}
      </div>
      <TaskCenterFilters query={query} />
      {items.length ? (
        <Card>
          <CardHeader>
            <h2 className='text-base leading-snug font-medium'>正式任务</h2>
            <CardDescription>共 {data.total} 条，按最近更新时间排序。</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            {items.map((item) => (
              <TaskCenterRow key={`${item.reference_type}:${item.reference_id}`} item={item} />
            ))}
            {data.pages > 1 ? (
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
                  <PaginationItem className='px-3 text-sm text-muted-foreground'>
                    第 {data.page} / {data.pages} 页
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
            ) : null}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <h2 className='text-base leading-snug font-medium'>
              {taskCenterEmptyState(hasAnyTasks, filtersActive).title}
            </h2>
            <CardDescription>
              {taskCenterEmptyState(hasAnyTasks, filtersActive).description}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              href={hasAnyTasks ? '/dashboard/runs' : '/dashboard/skills'}
              className={cn(buttonVariants())}
            >
              {taskCenterEmptyState(hasAnyTasks, filtersActive).action}
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
