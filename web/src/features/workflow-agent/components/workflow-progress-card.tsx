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
import { formatDate } from '@/lib/format';
import { taskErrorCategoryLabel } from '@/features/workflows/step-display';

interface WorkflowProgressCardProps {
  workflow: WorkflowRead;
  onOpenFetchedData?: () => void;
  compact?: boolean;
}

function nodeIcon(state: WorkflowFlowState): React.JSX.Element {
  if (state === 'complete') return <Icons.check className='size-4' aria-hidden='true' />;
  if (state === 'error') return <Icons.alertCircle className='size-4' aria-hidden='true' />;
  if (state === 'active')
    return <Icons.spinner className='size-4 animate-spin' aria-hidden='true' />;
  return <span className='size-2 rounded-full bg-current' aria-hidden='true' />;
}

function writeStatusLabel(value: unknown): string {
  if (value === 'not_started') return '尚未开始写入';
  if (value === 'verification_pending') return '已进入写入后校验，发布状态待核实';
  if (value === 'published') return '已有发布记录';
  return '待核实';
}

export function WorkflowProgressCard({
  workflow,
  onOpenFetchedData,
  compact = false
}: WorkflowProgressCardProps): React.JSX.Element {
  const nodes = workflowFlow(workflow);
  const groups = workflowSummaryFlow(workflow);
  const error = workflowError(workflow);
  const isFailed = workflow.state === 'failed' || workflow.stage === 'failed';
  const currentLabel =
    workflow.current_step_label ||
    (error
      ? `已在${error.step}中断`
      : isFailed
        ? '失败步骤待核实'
        : workflow.progress_message || '等待后台处理');

  return (
    <Card aria-live='polite' className='min-w-0'>
      <CardHeader>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <CardTitle>{compact ? <h3>日期进度</h3> : '任务进度'}</CardTitle>
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
        <ol className={compact ? 'platform-step-strip' : 'grid gap-2 sm:grid-cols-2 lg:grid-cols-5'} aria-label='任务五组流程'>
          {groups.map((group) => (
            <li key={group.key}>
              <div
                className={`${compact ? 'flex min-h-12 items-center gap-2 px-3 py-3 text-sm' : 'flex min-h-20 items-center gap-3 rounded-md border px-3 py-3 text-sm'} ${
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
                  <span className='min-w-0 break-words sm:mt-2 sm:block'>
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
              {error.reason && !error.message.includes(error.reason) && <p className='mt-2'>{error.reason}</p>}
              <p className='mt-2'>写入状态：{writeStatusLabel(workflow.step_error_detail?.write_status)}</p>
              <details className='mt-3'>
                <summary className='cursor-pointer text-sm'>错误详情</summary>
              <dl className='mt-3 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2'>
                <div>
                  <dt className='text-muted-foreground'>错误分类</dt>
                  <dd>{taskErrorCategoryLabel(workflow.step_error_detail?.category)}</dd>
                </div>
                <div>
                  <dt className='text-muted-foreground'>错误码</dt>
                  <dd>{typeof workflow.step_error_detail?.error_code === 'string' && workflow.step_error_detail.error_code.trim() ? workflow.step_error_detail.error_code : '待核实'}</dd>
                </div>
                <div>
                  <dt className='text-muted-foreground'>已发布材料版本</dt>
                  <dd>
                    {typeof workflow.step_error_detail?.published_material_version === 'number' ||
                    (typeof workflow.step_error_detail?.published_material_version === 'string' &&
                      workflow.step_error_detail.published_material_version.trim())
                      ? workflow.step_error_detail.published_material_version
                      : '待核实'}
                  </dd>
                </div>
                <div>
                  <dt className='text-muted-foreground'>是否允许恢复</dt>
                  <dd>
                    {workflow.step_error_detail?.recovery_allowed === true
                      ? '可以用当前材料版本新建任务'
                      : workflow.step_error_detail?.recovery_allowed === false
                        ? '当前不允许恢复'
                        : '待核实'}
                  </dd>
                </div>
                <div>
                  <dt className='text-muted-foreground'>发生时间</dt>
                  <dd>
                    {typeof workflow.step_error_detail?.failed_at === 'string' && workflow.step_error_detail.failed_at.trim()
                      ? formatDate(workflow.step_error_detail.failed_at, {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit'
                        }) + '（北京时间）'
                      : '待核实'}
                  </dd>
                </div>
              </dl>
              <a
                className='mt-3 inline-block text-sm underline underline-offset-2'
                href={`/dashboard/users?tab=audit&audit_resource_type=workflow&audit_resource_id=${encodeURIComponent(workflow.id)}`}
              >
                管理员审计查询
              </a>
              </details>
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
