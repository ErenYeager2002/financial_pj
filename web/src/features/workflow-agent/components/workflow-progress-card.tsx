'use client';

import * as React from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Icons } from '@/components/icons';
import {
  workflowError,
  workflowFlow,
  type WorkflowFlowState
} from '@/features/workflow-agent/workflow-flow';
import type { WorkflowRead } from '@/features/platform-api/types';

interface WorkflowProgressCardProps {
  workflow: WorkflowRead;
}

function nodeIcon(state: WorkflowFlowState): React.JSX.Element {
  if (state === 'complete') return <Icons.check className='size-4' aria-hidden='true' />;
  if (state === 'error') return <Icons.alertCircle className='size-4' aria-hidden='true' />;
  if (state === 'active')
    return <Icons.spinner className='size-4 animate-spin' aria-hidden='true' />;
  return <span className='size-2 rounded-full bg-current' aria-hidden='true' />;
}

export function WorkflowProgressCard({ workflow }: WorkflowProgressCardProps): React.JSX.Element {
  const nodes = workflowFlow(workflow);
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
        <ol className='grid gap-2 sm:grid-cols-3 lg:grid-cols-9' aria-label='后台任务流程'>
          {nodes.map((node, index) => (
            <li key={node.key} className='relative min-w-0'>
              {index < nodes.length - 1 && (
                <span
                  className={`absolute top-4 left-1/2 hidden h-px w-full sm:block ${
                    node.state === 'complete' ? 'bg-primary/60' : 'bg-border'
                  }`}
                  aria-hidden='true'
                />
              )}
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
              </div>
            </li>
          ))}
        </ol>
        {error && (
          <Alert variant='destructive' className='mt-4'>
            <AlertTitle>任务在此步骤中断：{error.step}</AlertTitle>
            <AlertDescription>
              <p className='whitespace-pre-wrap'>{error.message}</p>
              {(error.employee || error.skill || error.reason) && (
                <dl className='mt-3 grid gap-2 text-sm sm:grid-cols-3'>
                  {error.employee && (
                    <div>
                      <dt className='font-medium'>员工</dt>
                      <dd>{error.employee}</dd>
                    </div>
                  )}
                  {error.skill && (
                    <div>
                      <dt className='font-medium'>Skill</dt>
                      <dd>{error.skill}</dd>
                    </div>
                  )}
                  {error.reason && (
                    <div className='sm:col-span-3'>
                      <dt className='font-medium'>原因</dt>
                      <dd className='whitespace-pre-wrap'>{error.reason}</dd>
                    </div>
                  )}
                </dl>
              )}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
