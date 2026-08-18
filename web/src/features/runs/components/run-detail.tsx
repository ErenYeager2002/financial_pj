'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LoadingButton } from '@/components/ui/loading-button';
import { Progress, ProgressLabel } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { runKeys, runQueryOptions, runStepsQueryOptions } from '@/features/runs/api/queries';
import { retryRun } from '@/features/runs/api/service';
import type { PlatformRunDetail, PlatformRunEvent } from '@/features/runs/api/types';
import { parseRunOutputFiles } from '@/features/runs/run-output-files';
import {
  resultFieldLabel,
  runStateLabel,
  runStateVariant,
  TERMINAL_RUN_STATES
} from '@/features/runs/run-display';
import { formatDate } from '@/lib/format';
import { cn, formatBytes } from '@/lib/utils';
import { stepTypeLabel } from '@/features/workflows/step-display';

type ConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'complete';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function inputFileNames(files: Record<string, unknown>): Array<{ role: string; name: string }> {
  const result: Array<{ role: string; name: string }> = [];
  for (const [role, value] of Object.entries(files)) {
    const entries = Array.isArray(value) ? value : value ? [value] : [];
    for (const item of entries) {
      if (isRecord(item) && typeof item.name === 'string') result.push({ role, name: item.name });
    }
  }
  return result;
}

function metricText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  return JSON.stringify(value);
}

function eventLabel(type: string): string {
  const labels: Record<string, string> = {
    state: '状态',
    progress: '进度',
    notice: '提示',
    log: '处理记录'
  };
  return labels[type] ?? type;
}

function stepStateLabel(state: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '执行中',
    pending: '尚未开始',
    waiting_approval: '继续执行',
    waiting_confirmation: '等待确认',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
    timed_out: '已超时',
    skipped: '已跳过'
  };
  return labels[state] ?? state;
}

interface RunDetailViewProps {
  runId: string;
}

export function RunDetailView({ runId }: RunDetailViewProps): React.JSX.Element {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: run, refetch } = useSuspenseQuery(runQueryOptions(runId));
  const { data: steps, refetch: refetchSteps } = useSuspenseQuery({
    ...runStepsQueryOptions(runId),
    refetchInterval: TERMINAL_RUN_STATES.has(run.state) ? false : 5_000,
    refetchIntervalInBackground: false
  });
  const [events, setEvents] = useState<PlatformRunEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>(
    TERMINAL_RUN_STATES.has(run.state) ? 'complete' : 'connecting'
  );
  const seenEvents = useRef(new Set<number>());
  const retryMutation = useMutation({
    mutationFn: () => retryRun(run.id),
    onSuccess: async (retried) => {
      await queryClient.invalidateQueries({ queryKey: runKeys.all });
      router.push(`/dashboard/runs/${retried.id}`);
    }
  });

  useEffect(() => {
    const source = new EventSource(`/api/platform/runs/${encodeURIComponent(runId)}/events`);

    const handleEvent = (message: MessageEvent<string>) => {
      let event: PlatformRunEvent;
      try {
        event = JSON.parse(message.data) as PlatformRunEvent;
      } catch {
        return;
      }
      if (!Number.isSafeInteger(event.id) || seenEvents.current.has(event.id)) return;
      seenEvents.current.add(event.id);
      setEvents((current) => [...current, event].slice(-100));
      queryClient.setQueryData<PlatformRunDetail>(runQueryOptions(runId).queryKey, (current) =>
        current
          ? {
              ...current,
              state: event.state || current.state,
              progress: event.progress ?? current.progress,
              progress_message: event.message || current.progress_message
            }
          : current
      );
      if (TERMINAL_RUN_STATES.has(event.state)) {
        source.close();
        setConnection('complete');
        void refetch();
      }
      if (event.type === 'state' || TERMINAL_RUN_STATES.has(event.state)) {
        void refetchSteps();
      }
    };

    const handleOpen = () => setConnection('connected');
    const handleError = () => {
      setConnection('reconnecting');
      void refetch().then((result) => {
        if (result.data && TERMINAL_RUN_STATES.has(result.data.state)) {
          source.close();
          setConnection('complete');
          void refetchSteps();
        }
      });
    };
    source.addEventListener('open', handleOpen);
    source.addEventListener('error', handleError);
    for (const type of ['state', 'progress', 'notice', 'log']) {
      source.addEventListener(type, handleEvent as EventListener);
    }
    source.addEventListener('message', handleEvent as EventListener);

    return () => {
      source.removeEventListener('open', handleOpen);
      source.removeEventListener('error', handleError);
      for (const type of ['state', 'progress', 'notice', 'log']) {
        source.removeEventListener(type, handleEvent as EventListener);
      }
      source.removeEventListener('message', handleEvent as EventListener);
      source.close();
    };
  }, [queryClient, refetch, refetchSteps, runId]);

  const files = parseRunOutputFiles(run);
  const runFiles = run.files ?? {};
  const runParameters = run.parameters ?? {};
  const inputs = inputFileNames(runFiles);
  const summary = isRecord(run.result?.summary) ? run.result.summary : {};
  const labels = new Map(run.metric_specs.map((item) => [item.key, item.label]));
  const metrics = Object.entries(summary).map(([key, value]) => ({
    key,
    label: labels.get(key) ?? resultFieldLabel(key),
    value
  }));

  function handleRetry(): void {
    retryMutation.mutate();
  }

  return (
    <div className='space-y-4'>
      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-center gap-2'>
            <Badge variant={runStateVariant(run.state)}>{runStateLabel(run.state)}</Badge>
            <Badge variant='outline'>v{run.skill_version}</Badge>
            <Badge variant='outline'>
              {connection === 'connected'
                ? '实时更新中'
                : connection === 'reconnecting'
                  ? '正在重新连接'
                  : connection === 'complete'
                    ? '更新已结束'
                    : '正在连接'}
            </Badge>
          </div>
          <CardTitle className='text-xl'>{run.skill_name}</CardTitle>
          <CardDescription className='break-all'>任务编号：{run.id}</CardDescription>
        </CardHeader>
        <CardContent className='space-y-4'>
          <Progress value={run.progress}>
            <ProgressLabel>{run.progress_message || '等待状态更新'}</ProgressLabel>
            <span className='ml-auto text-sm text-muted-foreground tabular-nums'>
              {run.progress}%
            </span>
          </Progress>
          <div className='grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4'>
            <div>
              <p className='text-muted-foreground'>创建人</p>
              <p>{run.owner_name}</p>
            </div>
            <div>
              <p className='text-muted-foreground'>创建时间</p>
              <p>{formatDate(run.created_at, { hour: '2-digit', minute: '2-digit' })}</p>
            </div>
            <div>
              <p className='text-muted-foreground'>开始时间</p>
              <p>
                {formatDate(run.started_at ?? undefined, { hour: '2-digit', minute: '2-digit' }) ||
                  '—'}
              </p>
            </div>
            <div>
              <p className='text-muted-foreground'>完成时间</p>
              <p>
                {formatDate(run.finished_at ?? undefined, { hour: '2-digit', minute: '2-digit' }) ||
                  '—'}
              </p>
            </div>
          </div>
          {run.error_message && (
            <Alert variant='destructive'>
              <Icons.warning />
              <AlertTitle>任务执行失败</AlertTitle>
              <AlertDescription>{run.error_message}</AlertDescription>
            </Alert>
          )}
          {run.can_retry && (
            <div className='flex flex-wrap items-center gap-3'>
              <LoadingButton
                type='button'
                onClick={handleRetry}
                loading={retryMutation.isPending}
                loadingLabel='正在创建重试任务…'
              >
                重新执行
              </LoadingButton>
              <span className='text-sm text-muted-foreground'>
                将创建新任务，并重新核验权限、Skill 版本和输入文件。
              </span>
            </div>
          )}
          {!run.can_retry && run.error_message && run.retry_block_reason && (
            <p className='text-sm text-muted-foreground'>无法重试：{run.retry_block_reason}</p>
          )}
          {retryMutation.error && (
            <p className='text-sm text-destructive'>
              {retryMutation.error instanceof Error
                ? retryMutation.error.message
                : '任务重试失败。'}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>执行步骤</CardTitle>
          <CardDescription>按实际执行顺序显示当前任务的处理阶段。</CardDescription>
        </CardHeader>
        <CardContent>
          {steps.length ? (
            <ol className='space-y-0'>
              {steps.map((step, index) => (
                <li
                  key={step.id}
                  className='relative grid grid-cols-[2rem_1fr] gap-x-3 pb-5 last:pb-0'
                >
                  {index < steps.length - 1 && (
                    <span className='absolute top-7 bottom-0 left-[0.9375rem] w-px bg-border' />
                  )}
                  <span
                    className={cn(
                      'relative z-10 mt-0.5 flex size-8 items-center justify-center rounded-full border bg-background text-xs font-medium',
                      step.state === 'succeeded' &&
                        'border-primary bg-primary text-primary-foreground',
                      step.state === 'failed' && 'border-destructive text-destructive'
                    )}
                  >
                    {index + 1}
                  </span>
                  <div className='min-w-0 rounded-lg border p-3'>
                    <div className='flex flex-wrap items-center gap-2'>
                      <p className='font-medium'>{step.name}</p>
                      <Badge variant={step.state === 'failed' ? 'destructive' : 'outline'}>
                        {stepStateLabel(step.state)}
                      </Badge>
                      <span className='text-xs text-muted-foreground'>
                        {stepTypeLabel(step.step_type)}
                      </span>
                    </div>
                    <div className='mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground'>
                      <span>尝试次数：{step.attempt_count}</span>
                      {step.started_at && (
                        <span>
                          开始：
                          {formatDate(step.started_at, {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                          })}
                        </span>
                      )}
                      {step.finished_at && (
                        <span>
                          完成：
                          {formatDate(step.finished_at, {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                          })}
                        </span>
                      )}
                    </div>
                    {step.error_message && (
                      <p className='mt-2 text-sm text-destructive'>{step.error_message}</p>
                    )}
                    {step.can_retry && step.state === 'failed' && (
                      <p className='mt-1 text-xs text-muted-foreground'>此步骤满足安全重试条件。</p>
                    )}
                    {!step.can_retry && step.retry_block_reason && step.state === 'failed' && (
                      <p className='mt-1 text-xs text-muted-foreground'>
                        无法重试：{step.retry_block_reason}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className='text-muted-foreground'>该任务尚未生成分步执行记录。</p>
          )}
        </CardContent>
      </Card>

      <div className='grid gap-4 xl:grid-cols-2'>
        <Card>
          <CardHeader>
            <CardTitle>任务输入</CardTitle>
          </CardHeader>
          <CardContent className='space-y-4'>
            {inputs.length > 0 && (
              <div>
                <p className='mb-2 font-medium'>文件</p>
                <ul className='space-y-2'>
                  {inputs.map((file, index) => (
                    <li
                      key={`${file.role}-${index}`}
                      className='flex justify-between gap-3 rounded-lg border p-2'
                    >
                      <span className='text-muted-foreground'>{file.role}</span>
                      <span className='truncate'>{file.name}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {Object.keys(runParameters).length > 0 && (
              <div>
                <p className='mb-2 font-medium'>参数</p>
                <dl className='space-y-2'>
                  {Object.entries(runParameters).map(([key, value]) => (
                    <div key={key} className='flex justify-between gap-3 rounded-lg border p-2'>
                      <dt className='text-muted-foreground'>{resultFieldLabel(key)}</dt>
                      <dd>{metricText(value)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
            {run.message && (
              <div>
                <p className='mb-1 font-medium'>任务说明</p>
                <p className='whitespace-pre-wrap text-muted-foreground'>{run.message}</p>
              </div>
            )}
            {!inputs.length && !Object.keys(runParameters).length && !run.message && (
              <p className='text-muted-foreground'>此任务没有额外输入说明。</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>处理记录</CardTitle>
            <CardDescription>最多显示最近 100 条实时事件。</CardDescription>
          </CardHeader>
          <CardContent>
            {events.length ? (
              <ol className='max-h-96 space-y-3 overflow-y-auto pr-2'>
                {events.map((event) => (
                  <li key={event.id} className='grid grid-cols-[auto_1fr] gap-x-3'>
                    <span className='mt-1 size-2 rounded-full bg-primary' />
                    <div>
                      <div className='flex flex-wrap items-center gap-2'>
                        <span className='font-medium'>{eventLabel(event.type)}</span>
                        {event.progress !== null && (
                          <span className='text-xs text-muted-foreground'>{event.progress}%</span>
                        )}
                        <span className='text-xs text-muted-foreground'>
                          {formatDate(event.created_at, {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit'
                          })}
                        </span>
                      </div>
                      <p className='text-sm text-muted-foreground'>
                        {event.message || runStateLabel(event.state)}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className='text-muted-foreground'>
                {connection === 'complete' ? '暂无处理记录。' : '正在读取任务事件…'}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {(TERMINAL_RUN_STATES.has(run.state) || metrics.length > 0 || files.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle>任务结果</CardTitle>
            <CardDescription>结果文件下载会进行身份校验并记录审计。</CardDescription>
          </CardHeader>
          <CardContent className='space-y-5'>
            {metrics.length > 0 && (
              <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
                {metrics.map((metric) => (
                  <div key={metric.key} className='rounded-lg border p-3'>
                    <p className='text-sm text-muted-foreground'>{metric.label}</p>
                    <p className='mt-1 text-2xl font-semibold'>{metricText(metric.value)}</p>
                  </div>
                ))}
              </div>
            )}
            {metrics.length > 0 && files.length > 0 && <Separator />}
            {files.length > 0 ? (
              <div className='space-y-2'>
                {files.map((file) => (
                  <div
                    key={file.fileId}
                    className='flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3'
                  >
                    <div className='min-w-0'>
                      <p className='truncate font-medium'>{file.name}</p>
                      <p className='text-xs text-muted-foreground'>
                        {formatBytes(file.sizeBytes)}
                        {file.sha256 ? ` · SHA-256 ${file.sha256.slice(0, 12)}…` : ''}
                      </p>
                    </div>
                    <a
                      href={`/api/platform/runs/${encodeURIComponent(run.id)}/files/${encodeURIComponent(file.fileId)}`}
                      className={cn(buttonVariants({ variant: 'outline' }))}
                    >
                      <Icons.page />
                      下载结果
                    </a>
                  </div>
                ))}
              </div>
            ) : TERMINAL_RUN_STATES.has(run.state) ? (
              <p className='text-muted-foreground'>该任务没有可下载的结果文件。</p>
            ) : null}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
