'use client';

import * as React from 'react';
import Link from 'next/link';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { WorkflowProgressCard } from '@/features/workflow-agent/components/workflow-progress-card';
import type { WorkflowBatchRead } from '@/features/platform-api/types';

interface WorkflowBatchProgressProps {
  initialBatch: WorkflowBatchRead;
}

function terminal(batch: WorkflowBatchRead): boolean {
  return ['succeeded', 'failed', 'cancelled'].includes(batch.state);
}

export function WorkflowBatchProgress({
  initialBatch
}: WorkflowBatchProgressProps): React.JSX.Element {
  const [batch, setBatch] = React.useState(initialBatch);
  const [error, setError] = React.useState('');
  const [refreshing, setRefreshing] = React.useState(false);

  const refresh = React.useCallback(
    async (silent = false) => {
      if (!silent) setRefreshing(true);
      try {
        const response = await fetch(
          `/api/platform/workflow-batches/${encodeURIComponent(batch.id)}`,
          {
            cache: 'no-store'
          }
        );
        if (!response.ok) throw new Error('批次状态加载失败。');
        setBatch((await response.json()) as WorkflowBatchRead);
      } catch (refreshError) {
        if (!silent)
          setError(refreshError instanceof Error ? refreshError.message : '批次状态加载失败。');
      } finally {
        if (!silent) setRefreshing(false);
      }
    },
    [batch.id]
  );

  React.useEffect(() => {
    if (terminal(batch)) return;
    const timer = window.setInterval(() => void refresh(true), 2500);
    return () => window.clearInterval(timer);
  }, [batch, refresh]);

  const active = batch.workflows.find((workflow) =>
    ['running', 'waiting_confirmation'].includes(workflow.state)
  );

  return (
    <div className='space-y-4'>
      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-start justify-between gap-3'>
            <div>
              <CardTitle>{batch.skill_name}</CardTitle>
              <CardDescription className='mt-1'>
                已选择 {batch.reconciliation_dates.length} 天，按日期顺序处理
              </CardDescription>
            </div>
            <Badge variant={batch.state === 'failed' ? 'destructive' : 'secondary'}>
              {batch.progress}%
            </Badge>
          </div>
          <Progress
            value={batch.progress}
            aria-label={`批次进度 ${batch.progress}%`}
            className='mt-3'
          />
          <p className='text-sm text-muted-foreground'>{batch.progress_message}</p>
        </CardHeader>
      </Card>

      {batch.error_message && (
        <Alert variant='destructive'>
          <AlertTitle>批次已暂停</AlertTitle>
          <AlertDescription>{batch.error_message}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className='text-base'>日期任务</CardTitle>
          <CardDescription>展开当前日期可以看到具体步骤和失败位置。</CardDescription>
        </CardHeader>
        <CardContent className='space-y-3'>
          {batch.workflows.map((workflow) => (
            <div key={workflow.id} className='rounded-lg border p-3'>
              <div className='mb-3 flex flex-wrap items-center justify-between gap-2'>
                <div className='flex items-center gap-2 text-sm font-medium'>
                  <span className='flex size-7 items-center justify-center rounded-full bg-muted text-xs'>
                    {workflow.batch_sequence}
                  </span>
                  {workflow.reconciliation_date}
                </div>
                <Link
                  href={`/dashboard/workflows/${encodeURIComponent(workflow.id)}`}
                  className='text-xs text-primary underline-offset-4 hover:underline'
                >
                  查看任务
                </Link>
              </div>
              <WorkflowProgressCard workflow={workflow} />
            </div>
          ))}
        </CardContent>
      </Card>

      {active && (
        <p className='text-sm text-muted-foreground' role='status' aria-live='polite'>
          当前处理：{active.reconciliation_date} ·{' '}
          {active.current_step_label || active.progress_message}
        </p>
      )}
      {error && (
        <p className='text-sm text-destructive' role='alert'>
          {error}
        </p>
      )}
      <div className='flex flex-wrap gap-2'>
        <Button
          type='button'
          variant='outline'
          onClick={() => void refresh()}
          disabled={refreshing}
        >
          {refreshing ? '刷新中…' : '刷新状态'}
        </Button>
        <Button
          type='button'
          variant='ghost'
          onClick={() => window.location.assign('/dashboard/workflows')}
        >
          返回任务列表
        </Button>
      </div>
    </div>
  );
}
