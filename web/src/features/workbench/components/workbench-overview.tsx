import Link from 'next/link';
import { Heading } from '@/components/ui/heading';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import type { PlatformHealth, Workbench } from '@/features/platform-api/types';
import { taskCenterStateLabel } from '@/features/task-center/presentation';
import { formatDate } from '@/lib/format';
import { cn, formatBytes } from '@/lib/utils';

export function WorkbenchOverview({ data, health }: { data: Workbench; health: PlatformHealth }) {
  const commonSkills = data.common_skills ?? [];
  const pendingTasks = data.pending_tasks ?? [];
  const recentTasks = data.recent_tasks ?? [];
  const recentFiles = data.recent_files ?? [];
  const runtime = data.runtime ?? health;
  const configuredCapacity = Object.values(runtime.configured_workers ?? {}).reduce(
    (total, value) => total + Math.max(0, value),
    0
  );
  const onlineCapacity = Object.values(runtime.online_workers ?? {}).reduce(
    (total, value) => total + Math.max(0, value),
    0
  );
  const queueDepth = Object.values(runtime.queue_depth ?? {}).reduce(
    (total, value) => total + Math.max(0, value),
    0
  );
  const taskReminders = data.task_reminders ?? {
    pending_dates: 0,
    active_skills: 0,
    failed_checks: 0
  };
  const cards = [
    ['待确认任务', data.counts.waiting_confirmation],
    ['正在处理', data.counts.active],
    ['已完成', data.counts.succeeded],
    ['失败或超时', data.counts.failed]
  ] as const;

  return (
    <div className='space-y-6'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div>
          <Heading title='我的工作台' description='' level={1} compact />
        </div>
        <Link href='/dashboard/skills' className={cn(buttonVariants(), 'platform-action')}>
          创建任务
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <div>
              <CardTitle><h2>任务提醒</h2></CardTitle>
              <CardDescription>
                {taskReminders.pending_dates
                  ? `${taskReminders.active_skills} 个 Skill 有 ${taskReminders.pending_dates} 个待处理日期`
                  : '当前没有待处理日期'}
                {taskReminders.failed_checks
                  ? `，另有 ${taskReminders.failed_checks} 次检查失败`
                  : ''}
              </CardDescription>
            </div>
            <Link
              href='/dashboard/runs'
              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'platform-action')}
            >
              打开任务中心
            </Link>
          </div>
        </CardHeader>
      </Card>



      <PaginatedCollection
        ariaLabel='任务概览'
        contentClassName='platform-metrics'
      >
        {cards.map(([label, value]) => (
          <Card key={label}>
            <CardHeader>
              <CardDescription>{label}</CardDescription>
              <CardTitle className='text-3xl tabular-nums'>{value}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </PaginatedCollection>

      <div className='platform-workbench-grid'>
        <Card>
          <CardHeader>
            <CardTitle><h2>待处理任务</h2></CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            {pendingTasks.length ? (
              <PaginatedCollection ariaLabel='待处理任务' contentClassName='platform-list'>
                {pendingTasks.map((task) => (
                <Link
                  key={`${task.reference_type}:${task.reference_id}`}
                  href={task.detail_href}
                  className='platform-row transition-colors hover:bg-muted/50'
                >
                  <div className='min-w-0'>
                    <p className='font-medium break-words'>{task.skill_name}</p>
                    <p className='text-sm text-muted-foreground break-words'>
                      {task.progress_message || '等待处理'}
                    </p>
                  </div>
                  <Badge variant={task.view_state === 'failed' ? 'destructive' : 'outline'}>
                    {taskCenterStateLabel(task.view_state)}
                  </Badge>
                </Link>
                ))}
              </PaginatedCollection>
            ) : (
              <p className='text-sm text-muted-foreground'>当前没有需要处理的任务。</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle><h2>常用 Skill</h2></CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            {commonSkills.length ? (
              <PaginatedCollection ariaLabel='常用 Skill' contentClassName='platform-list'>
                {commonSkills.map((item) => (
                <div
                  key={item.skill.id}
                  className='platform-row'
                >
                  <div className='min-w-0'>
                    <p className='font-medium break-words'>{item.skill.name}</p>
                    <p className='text-sm text-muted-foreground break-words'>
                      {item.skill.output_summary}
                    </p>
                  </div>
                  <div className='flex shrink-0 flex-wrap items-center justify-end gap-2'>
                    <Badge variant='outline'>使用 {item.run_count} 次</Badge>
                    <Link
                      href={`/dashboard/skills/${encodeURIComponent(item.skill.id)}/run`}
                      className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'platform-action')}
                    >
                      运行
                    </Link>
                  </div>
                </div>
                ))}
              </PaginatedCollection>
            ) : (
              <p className='text-sm text-muted-foreground'>当前没有可用的 Skill。</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle><h2>最近结果</h2></CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            {recentTasks.length ? (
              <PaginatedCollection ariaLabel='最近结果' contentClassName='platform-list'>
                {recentTasks.map((task) => (
                <Link
                  key={`${task.reference_type}:${task.reference_id}`}
                  href={task.detail_href}
                  className='platform-row transition-colors hover:bg-muted/50'
                >
                  <div>
                    <p className='font-medium'>{task.skill_name}</p>
                    <p className='text-sm text-muted-foreground'>
                      {formatDate(task.updated_at, {
                        hour: '2-digit',
                        minute: '2-digit'
                      })}
                    </p>
                  </div>
                  <Badge variant='secondary'>{taskCenterStateLabel(task.view_state)}</Badge>
                </Link>
                ))}
              </PaginatedCollection>
            ) : (
              <p className='text-sm text-muted-foreground'>还没有已完成的任务。</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle><h2>最近文件</h2></CardTitle>
            <CardDescription>共 {data.counts.files} 个可见文件</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            {recentFiles.length ? (
              <PaginatedCollection ariaLabel='最近文件' contentClassName='platform-list'>
                {recentFiles.map((file) => (
                <div
                  key={file.id}
                  className='platform-row'
                >
                  <div className='min-w-0'>
                    <p className='font-medium break-words'>{file.name}</p>
                    <p className='text-sm text-muted-foreground'>{formatBytes(file.size_bytes)}</p>
                  </div>
                  <Badge variant='outline'>{file.kind === 'output' ? '结果' : '上传'}</Badge>
                </div>
                ))}
              </PaginatedCollection>
            ) : (
              <p className='text-sm text-muted-foreground'>当前没有文件。</p>
            )}
            <Link
              href='/dashboard/files'
              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'platform-action w-full')}
            >
              查看文件中心
            </Link>
          </CardContent>
        </Card>
      </div>
      <Card id='environment-health' className='scroll-mt-6'>
        <CardHeader>
          <div className='flex flex-wrap items-start justify-between gap-3'>
            <div>
              <CardTitle><h2>运行环境状态</h2></CardTitle>
            </div>
            <Badge variant={runtime.readiness === 'ready' ? 'secondary' : 'outline'}>
              {runtime.readiness === 'ready'
                ? '已就绪'
                : runtime.readiness === 'not_ready'
                  ? '未就绪'
                  : '状态未知'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className='space-y-3'>
          <dl className='platform-environment-metrics'>
            <div className='min-w-0'>
              <dt className='text-sm text-muted-foreground'>注册 Skill</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>{health.skills}</dd>
            </div>
            <div className='min-w-0'>
              <dt className='text-sm text-muted-foreground'>已配置执行容量</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>
                {configuredCapacity}
              </dd>
            </div>
            <div className='min-w-0'>
              <dt className='text-sm text-muted-foreground'>当前在线容量</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>
                {onlineCapacity}
              </dd>
            </div>
            <div className='min-w-0'>
              <dt className='text-sm text-muted-foreground'>排队任务</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>{queueDepth}</dd>
            </div>
            <div className='min-w-0'>
              <dt className='text-sm text-muted-foreground'>依赖检查</dt>
              <dd className='mt-1 text-lg font-semibold'>
                {runtime.dependency_status === 'not_checked'
                  ? '未检查'
                  : runtime.dependency_status === 'available'
                    ? '可用'
                    : runtime.dependency_status === 'unavailable'
                      ? '不可用'
                      : '未知'}
              </dd>
            </div>
          </dl>
          {runtime.workers?.length ? (
            <div className='platform-list'>
              {runtime.workers.map((worker) => (
                <div key={worker.pool} className='py-3 text-sm'>
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <span>{worker.pool}</span>
                    <Badge variant={worker.state === 'online' ? 'secondary' : 'outline'}>
                      {worker.state === 'online'
                        ? '有近期心跳'
                        : worker.state === 'expired'
                          ? '心跳已过期'
                          : '未检查'}
                    </Badge>
                  </div>
                  <p className='mt-1 text-xs text-muted-foreground'>
                    排队 {worker.queued_count} · 处理中 {worker.running_count}
                    {worker.last_heartbeat_at
                      ? ` · 最近 ${formatDate(worker.last_heartbeat_at)}`
                      : ''}
                  </p>
                </div>
              ))}
            </div>
          ) : null}
          <p className='text-sm text-muted-foreground'>
            {runtime.scope || '当前没有可用的执行环境检查结果。'}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
