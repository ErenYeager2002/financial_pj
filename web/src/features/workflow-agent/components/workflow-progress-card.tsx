'use client';

import * as React from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Icons } from '@/components/icons';
import {
  workflowError,
  workflowFlow,
  workflowSummaryFlow,
  type WorkflowFlowState
} from '@/features/workflow-agent/workflow-flow';
import type { WorkflowRead } from '@/features/platform-api/types';

interface WorkflowProgressCardProps {
  workflow: WorkflowRead;
  onOpenFetchedData?: () => void;
}

function nodeIcon(state: WorkflowFlowState): React.JSX.Element {
  if (state === 'complete') return <Icons.check className='size-4' aria-hidden='true' />;
  if (state === 'error') return <Icons.alertCircle className='size-4' aria-hidden='true' />;
  if (state === 'active')
    return <Icons.spinner className='size-4 animate-spin' aria-hidden='true' />;
  return <span className='size-2 rounded-full bg-current' aria-hidden='true' />;
}

export function WorkflowProgressCard({
  workflow,
  onOpenFetchedData
}: WorkflowProgressCardProps): React.JSX.Element {
  const nodes = workflowFlow(workflow);
  const groups = workflowSummaryFlow(workflow);
  const error = workflowError(workflow);
  const currentLabel =
    workflow.current_step_label || workflow.progress_message || '等待后台 Worker';

  return (
    <Card aria-live='polite'>
      <CardHeader>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <CardTitle>任务进度</CardTitle>
            <CardDescription className='mt-1'>{currentLabel}</CardDescription>
          </div>
          <Badge
            variant={
              error ? 'destructive' : workflow.state === 'succeeded' ? 'secondary' : 'outline'
            }
          >
            {workflow.progress}%
          </Badge>
        </div>
        <Progress
          value={workflow.progress}
          aria-label={`任务进度 ${workflow.progress}%`}
          className='mt-3'
        />
      </CardHeader>
      <CardContent>
        <ol className='grid gap-2 sm:grid-cols-2 lg:grid-cols-5' aria-label='任务五组流程'>
          {groups.map((group) => (
            <li key={group.key}>
              <div
                className={`flex min-h-20 items-center gap-3 rounded-md border px-3 py-3 text-sm ${
                  group.state === 'error'
                    ? 'border-destructive/60 bg-destructive/10 text-destructive'
                    : group.state === 'active'
                      ? 'border-primary/60 bg-primary/5 text-foreground'
                      : group.state === 'complete'
                        ? 'border-primary/30 bg-primary/5 text-foreground'
                        : 'text-muted-foreground'
                }`}
              >
                <span className='flex size-8 shrink-0 items-center justify-center rounded-full border bg-background'>
                  {nodeIcon(group.state)}
                </span>
                <span className='min-w-0 font-medium'>{group.label}</span>
              </div>
            </li>
          ))}
        </ol>
        <details className='mt-3 rounded-md border px-3 py-2'>
          <summary className='cursor-pointer text-sm font-medium'>查看细分步骤</summary>
          <ol
            className='mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-5'
            aria-label='任务细分流程'
          >
            {nodes.map((node) => (
              <li key={node.key} className='relative min-w-0'>
                <div
                  className={`relative flex items-center gap-2 rounded-md border px-2 py-2 text-xs sm:block sm:text-center ${
                    node.state === 'error'
                      ? 'border-destructive/60 bg-destructive/10 text-destructive'
                      : node.state === 'active'
                        ? 'border-primary/60 bg-primary/5 text-foreground'
                        : node.state === 'complete'
                          ? 'border-primary/30 bg-primary/5 text-foreground'
                          : 'text-muted-foreground'
                  }`}
                >
                  <span className='mx-auto flex size-8 shrink-0 items-center justify-center rounded-full border bg-background'>
                    {nodeIcon(node.state)}
                  </span>
                  <span className='min-w-0 truncate sm:mt-2 sm:block sm:whitespace-normal'>
                    {node.label}
                  </span>
                  {(node.key === 'fetch_zhiyun' || node.key === 'review_fetched_data') &&
                    workflow.fetched_data_available &&
                    onOpenFetchedData && (
                      <Button
                        type='button'
                        size='xs'
                        variant='outline'
                        className='relative mt-2 w-full sm:text-xs'
                        onClick={onOpenFetchedData}
                      >
                        查看取数数据
                      </Button>
                    )}
                </div>
              </li>
            ))}
          </ol>
        </details>
        {error && (
          <Alert variant='destructive' className='mt-4'>
            <AlertTitle>任务在此步骤中断：{error.step}</AlertTitle>
            <AlertDescription>
              <p className='whitespace-pre-wrap'>{error.message}</p>
              {error.reason && <p className='mt-2'>{error.reason}</p>}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
