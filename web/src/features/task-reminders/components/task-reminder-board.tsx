'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import { Input } from '@/components/ui/input';
import type { TaskReminderBoard } from '@/features/platform-api/types';
import { actionableReminderDates, taskReminderWorkflowHref } from '@/features/task-reminders/links';
import {
  manualCheckDateBounds,
  taskReminderBoardVisibility
} from '@/features/task-reminders/task-reminder-board-presentation';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';

function responseMessage(response: Response): Promise<string> {
  return response
    .json()
    .then((body: unknown) =>
      body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
        ? body.detail
        : '重试排队失败。'
    )
    .catch(() => '重试排队失败。');
}

export function TaskReminderBoardView({ data }: { data: TaskReminderBoard }) {
  const router = useRouter();
  const [retrying, setRetrying] = React.useState('');
  const [error, setError] = React.useState('');
  const [manualDate, setManualDate] = React.useState('');
  const failures = data.check_failures ?? [];
  const resolvedCount = data.resolved_count ?? 0;
  const visibility = taskReminderBoardVisibility(data.reminders ?? [], failures);
  const dateBounds = React.useMemo(() => manualCheckDateBounds(), []);
  const groups = React.useMemo(() => {
    const source = data.reminders ?? [];
    const grouped = new Map<string, typeof source>();
    for (const reminder of source) {
      const key = `${reminder.skill_id}:${reminder.owner_id}`;
      grouped.set(key, [...(grouped.get(key) ?? []), reminder]);
    }
    return [...grouped.values()];
  }, [data.reminders]);

  async function retry(checkId: string) {
    setRetrying(checkId);
    setError('');
    try {
      const response = await fetch(
        `/api/platform/task-reminders/checks/${encodeURIComponent(checkId)}/retry`,
        { method: 'POST' }
      );
      if (!response.ok) throw new Error(await responseMessage(response));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '重试排队失败。');
    } finally {
      setRetrying('');
    }
  }

  async function checkDate() {
    if (!manualDate) return;
    setRetrying('manual');
    setError('');
    try {
      const response = await fetch('/api/platform/task-reminders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skill_id: 'ar-hexiao-daily',
          business_dates: [manualDate]
        })
      });
      if (!response.ok) throw new Error(await responseMessage(response));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '补查排队失败。');
    } finally {
      setRetrying('');
    }
  }

  async function clearResolved() {
    setRetrying('cleanup');
    setError('');
    try {
      const response = await fetch('/api/platform/task-reminders', { method: 'DELETE' });
      if (!response.ok) throw new Error(await responseMessage(response));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '已处理成功提醒清理失败。');
    } finally {
      setRetrying('');
    }
  }

  return (
    <div className='space-y-4'>
      {error ? (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      ) : null}
      {resolvedCount > 0 ? (
        <div className='flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50/50 px-4 py-3 dark:border-emerald-900 dark:bg-emerald-950/20'>
          <div>
            <p className='text-sm font-medium'>已处理成功 {resolvedCount} 个日期</p>
            <p className='text-sm text-muted-foreground'>成功日期已从待处理列表移除。</p>
          </div>
          <Button
            size='sm'
            variant='outline'
            disabled={retrying === 'cleanup'}
            onClick={() => void clearResolved()}
          >
            {retrying === 'cleanup' ? '正在清理' : '清理已处理成功'}
          </Button>
        </div>
      ) : null}
      {visibility.showIdle ? (
        <div className='flex flex-wrap items-center justify-between gap-2 rounded-lg border px-4 py-3'>
          <div>
            <h2 className='text-sm font-medium'>任务提醒</h2>
            <p className='text-sm text-muted-foreground'>当前没有待处理日期或检查异常。</p>
          </div>
          <Badge variant='secondary'>暂无提醒</Badge>
        </div>
      ) : null}
      {visibility.showPending ? (
        <PaginatedCollection ariaLabel='待处理任务提醒' contentClassName='space-y-4'>
          {groups.map((reminders) => {
            const first = reminders[0];
            const actionableDates = actionableReminderDates(reminders);
            return (
              <Card key={`${first.skill_id}:${first.owner_id}`}>
                <CardHeader>
                  <div className='flex flex-wrap items-start justify-between gap-3'>
                    <div>
                      <h2 className='text-base leading-snug font-medium'>{first.skill_name}</h2>
                      <CardDescription>
                        负责人：{first.owner_name} · {reminders.length} 个未成功日期
                      </CardDescription>
                    </div>
                    <div className='flex items-center gap-2'>
                      <Badge variant='secondary'>{reminders.length} 天</Badge>
                      {actionableDates.length ? (
                        <Link
                          href={taskReminderWorkflowHref(first.skill_id, actionableDates)}
                          className={cn(buttonVariants({ size: 'sm' }))}
                        >
                          处理这些日期
                        </Link>
                      ) : null}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className='space-y-2'>
                  <PaginatedCollection
                    ariaLabel={`${first.skill_name}待处理日期`}
                    contentClassName='space-y-2'
                  >
                    {reminders.map((reminder) => (
                      <div
                        key={reminder.id}
                        role='listitem'
                        className='flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3'
                      >
                        <div>
                          <p className='font-medium'>{reminder.business_date}</p>
                          <p className='text-sm text-muted-foreground'>
                            {reminder.record_count} 条回款 · 最近检查{' '}
                            {formatDate(reminder.last_checked_at, {
                              hour: '2-digit',
                              minute: '2-digit'
                            })}
                          </p>
                        </div>
                        <div className='flex items-center gap-2'>
                          {reminder.reopened ? (
                            <Badge variant='destructive'>数据有变化</Badge>
                          ) : null}
                          {reminder.state === 'in_progress' && reminder.workflow_id ? (
                            <Link
                              href={`/dashboard/workflows/${encodeURIComponent(reminder.workflow_id)}`}
                              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                            >
                              查看任务
                            </Link>
                          ) : (
                            <Link
                              href={taskReminderWorkflowHref(reminder.skill_id, [
                                reminder.business_date
                              ])}
                              className={cn(buttonVariants({ size: 'sm' }))}
                            >
                              去做任务
                            </Link>
                          )}
                        </div>
                      </div>
                    ))}
                  </PaginatedCollection>
                </CardContent>
              </Card>
            );
          })}
        </PaginatedCollection>
      ) : null}
      {visibility.showFailures ? (
        <PaginatedCollection ariaLabel='任务检查失败记录' contentClassName='space-y-4'>
          {failures.map((failure) => (
            <Card
              key={failure.id}
              role='alert'
              aria-live='polite'
              className='border-destructive/40'
            >
              <CardHeader>
                <h2 className='text-base leading-snug font-medium'>任务检查失败</h2>
                <CardDescription>
                  {failure.skill_name} · {failure.owner_name} ·{' '}
                  {(failure.business_dates ?? []).join('、')}
                </CardDescription>
              </CardHeader>
              <CardContent className='flex flex-wrap items-center justify-between gap-3'>
                <div className='space-y-1 text-sm'>
                  <p className='text-destructive'>
                    {failure.error_message || '检查未完成，可稍后重试。'}
                  </p>
                  <p className='text-muted-foreground'>已尝试 {failure.attempt_count} 次。</p>
                </div>
                <Button
                  size='sm'
                  variant='outline'
                  disabled={retrying === failure.id}
                  onClick={() => void retry(failure.id)}
                >
                  {retrying === failure.id ? '正在排队' : '重试检查'}
                </Button>
              </CardContent>
            </Card>
          ))}
        </PaginatedCollection>
      ) : null}
      <section className='rounded-lg border px-4 py-3' aria-labelledby='manual-check-date-title'>
        <h2 id='manual-check-date-title' className='text-sm font-medium'>
          手动补查日期
        </h2>
        <div className='mt-3 flex flex-wrap items-end gap-2'>
          <label htmlFor='task-reminder-manual-date' className='grid gap-1 text-sm'>
            <span className='text-muted-foreground'>最近 31 天内的日期</span>
            <Input
              id='task-reminder-manual-date'
              type='date'
              min={dateBounds.min}
              max={dateBounds.max}
              value={manualDate}
              onChange={(event) => setManualDate(event.target.value)}
            />
          </label>
          <Button
            size='sm'
            variant='outline'
            disabled={!manualDate || retrying === 'manual'}
            onClick={() => void checkDate()}
          >
            {retrying === 'manual' ? '正在排队' : '补查日期'}
          </Button>
        </div>
      </section>
    </div>
  );
}
