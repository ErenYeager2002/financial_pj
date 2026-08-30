import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { PlatformHealth, Workbench } from '@/features/platform-api/types';
import { runStateLabel, runStateVariant } from '@/features/runs/run-display';
import { formatDate } from '@/lib/format';
import { cn, formatBytes } from '@/lib/utils';

export function WorkbenchOverview({ data, health }: { data: Workbench; health: PlatformHealth }) {
  const commonSkills = data.common_skills ?? [];
  const pendingRuns = data.pending_runs ?? [];
  const recentResults = data.recent_results ?? [];
  const recentFiles = data.recent_files ?? [];
  const taskReminders = data.task_reminders ?? {
    pending_dates: 0,
    active_skills: 0,
    failed_checks: 0
  };
  const cards = [
    ['待确认任务', data.counts.waiting_confirmation, '需要确认后才会进入执行队列'],
    ['正在处理', data.counts.active, '排队或正在执行的任务'],
    ['已完成', data.counts.succeeded, '当前可见范围内的成功任务'],
    ['失败或超时', data.counts.failed, '可在任务详情查看原因和重试条件']
  ] as const;

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div>
          <h2 className='text-2xl font-bold tracking-tight'>我的工作台</h2>
          <p className='text-muted-foreground'>常用财务工具、待处理任务和最近结果</p>
        </div>
        <Link href='/dashboard/skills' className={cn(buttonVariants())}>
          创建任务
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <div>
              <CardTitle>任务提醒</CardTitle>
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
              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
            >
              打开任务中心
            </Link>
          </div>
        </CardHeader>
      </Card>

      <Card id='environment-health' className='scroll-mt-6'>
        <CardHeader>
          <div className='flex flex-wrap items-start justify-between gap-3'>
            <div>
              <CardTitle>运行环境状态</CardTitle>
              <CardDescription>
                平台服务{health.status === 'ok' ? '正常' : '异常'}，仅展示不含敏感配置的汇总信息
              </CardDescription>
            </div>
            <Badge variant={health.status === 'ok' ? 'secondary' : 'destructive'}>
              {health.status === 'ok' ? '正常' : '需检查'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className='space-y-3'>
          <dl className='grid gap-3 sm:grid-cols-2 xl:grid-cols-4'>
            <div className='rounded-lg border p-3'>
              <dt className='text-sm text-muted-foreground'>注册 Skill</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>{health.skills}</dd>
            </div>
            <div className='rounded-lg border p-3'>
              <dt className='text-sm text-muted-foreground'>已配置 Worker 组</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>
                {Object.values(health.configured_workers).filter((count) => count > 0).length}
              </dd>
            </div>
            <div className='rounded-lg border p-3'>
              <dt className='text-sm text-muted-foreground'>执行容量</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>
                {health.configured_execution_capacity}
              </dd>
            </div>
            <div className='rounded-lg border p-3'>
              <dt className='text-sm text-muted-foreground'>注册异常</dt>
              <dd className='mt-1 text-2xl font-semibold tabular-nums'>
                {health.registry_errors?.length ?? 0}
              </dd>
            </div>
          </dl>
          <p className='text-sm text-muted-foreground'>
            Office、LibreOffice
            等系统依赖的详细检查需由受控系统诊断适配器执行；该能力上线前，环境诊断 Skill 保持停用。
          </p>
        </CardContent>
      </Card>

      <div className='grid gap-4 sm:grid-cols-2 xl:grid-cols-4'>
        {cards.map(([label, value, description]) => (
          <Card key={label}>
            <CardHeader>
              <CardDescription>{label}</CardDescription>
              <CardTitle className='text-3xl tabular-nums'>{value}</CardTitle>
            </CardHeader>
            <CardContent className='text-sm text-muted-foreground'>{description}</CardContent>
          </Card>
        ))}
      </div>

      <div className='grid gap-4 xl:grid-cols-2'>
        <Card>
          <CardHeader>
            <CardTitle>常用 Skill</CardTitle>
            <CardDescription>按当前可见范围内的使用次数排序</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            {commonSkills.length ? (
              commonSkills.map((item) => (
                <div
                  key={item.skill.id}
                  className='flex items-center justify-between gap-3 rounded-lg border p-3'
                >
                  <div className='min-w-0'>
                    <p className='truncate font-medium'>{item.skill.name}</p>
                    <p className='truncate text-sm text-muted-foreground'>
                      {item.skill.output_summary}
                    </p>
                  </div>
                  <div className='flex shrink-0 items-center gap-2'>
                    <Badge variant='outline'>使用 {item.run_count} 次</Badge>
                    <Link
                      href={`/dashboard/skills/${encodeURIComponent(item.skill.id)}/run`}
                      className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                    >
                      运行
                    </Link>
                  </div>
                </div>
              ))
            ) : (
              <p className='text-sm text-muted-foreground'>当前没有可用的 Skill。</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>待处理任务</CardTitle>
            <CardDescription>等待确认、失败或超时的最近任务</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            {pendingRuns.length ? (
              pendingRuns.map((run) => (
                <Link
                  key={run.id}
                  href={`/dashboard/runs/${run.id}`}
                  className='flex items-center justify-between gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/50'
                >
                  <div className='min-w-0'>
                    <p className='truncate font-medium'>{run.skill_name}</p>
                    <p className='truncate text-sm text-muted-foreground'>
                      {run.error_message || run.progress_message || '等待处理'}
                    </p>
                  </div>
                  <Badge variant={runStateVariant(run.state)}>{runStateLabel(run.state)}</Badge>
                </Link>
              ))
            ) : (
              <p className='text-sm text-muted-foreground'>当前没有需要处理的任务。</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>最近结果</CardTitle>
            <CardDescription>最近完成的五个任务</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            {recentResults.length ? (
              recentResults.map((run) => (
                <Link
                  key={run.id}
                  href={`/dashboard/runs/${run.id}`}
                  className='flex items-center justify-between gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/50'
                >
                  <div>
                    <p className='font-medium'>{run.skill_name}</p>
                    <p className='text-sm text-muted-foreground'>
                      {formatDate(run.finished_at ?? run.created_at, {
                        hour: '2-digit',
                        minute: '2-digit'
                      })}
                    </p>
                  </div>
                  <Badge variant='secondary'>已完成</Badge>
                </Link>
              ))
            ) : (
              <p className='text-sm text-muted-foreground'>还没有已完成的任务。</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>最近文件</CardTitle>
            <CardDescription>共 {data.counts.files} 个可见文件</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            {recentFiles.length ? (
              recentFiles.map((file) => (
                <div
                  key={file.id}
                  className='flex items-center justify-between gap-3 rounded-lg border p-3'
                >
                  <div className='min-w-0'>
                    <p className='truncate font-medium'>{file.name}</p>
                    <p className='text-sm text-muted-foreground'>{formatBytes(file.size_bytes)}</p>
                  </div>
                  <Badge variant='outline'>{file.kind === 'output' ? '结果' : '上传'}</Badge>
                </div>
              ))
            ) : (
              <p className='text-sm text-muted-foreground'>当前没有文件。</p>
            )}
            <Link
              href='/dashboard/files'
              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-full')}
            >
              查看文件中心
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
