'use client';

import * as React from 'react';
import Link from 'next/link';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import { Progress } from '@/components/ui/progress';
import { WorkflowProgressCard } from '@/features/workflow-agent/components/workflow-progress-card';
import { WorkflowFetchedDataDialog } from '@/features/workflow-agent/components/workflow-fetched-data-dialog';
import type { WorkflowBatchRead } from '@/features/platform-api/types';
import {
  batchFailureGuidance,
  currentWorkflowForBatch,
  isTerminalWorkflow,
  isWaitingWorkflow,
  preferredWorkflowForBatch,
  workflowAttentionHint,
  workflowStatusInBatch,
  workflowStatusLabel,
  workflowStepLabel
} from '@/features/workflow-agent/workflow-batch-selection';

interface WorkflowBatchProgressProps {
  initialBatch: WorkflowBatchRead;
}

function terminal(batch: WorkflowBatchRead): boolean {
  return ['succeeded', 'failed', 'cancelled'].includes(batch.state);
}

function batchStatusLabel(batch: WorkflowBatchRead): string {
  if (batch.state === 'succeeded') return '已完成';
  if (batch.state === 'failed') return '失败';
  if (batch.state === 'cancelled') return '已取消';
  const focus = preferredWorkflowForBatch(batch);
  if (focus) return workflowStatusLabel(focus);
  if (batch.state === 'running') return '处理中';
  return '等待';
}

function statusClass(status: string): string {
  if (status === '失败') return 'border-destructive/50 bg-destructive/10 text-destructive';
  if (status === '待检查取数' || status === '待确认写入') {
    return 'border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300';
  }
  if (status === '处理中') return 'border-primary/50 bg-primary/10 text-primary';
  if (status === '已完成') {
    return 'border-emerald-600/30 bg-emerald-600/10 text-emerald-700 dark:text-emerald-300';
  }
  if (status === '已取消') return 'border-muted-foreground/30 bg-muted text-muted-foreground';
  return 'border-border bg-muted/50 text-muted-foreground';
}

function resultSummaryValue(summary: Record<string, unknown>, key: string): string {
  const value = summary[key];
  return value === undefined || value === null || value === '' ? '未提供' : String(value);
}

interface BatchOutputFile {
  fileId: string;
  name: string;
}

function batchOutputFiles(batch: WorkflowBatchRead): BatchOutputFile[] {
  return batch.workflows.flatMap((workflow) =>
    workflow.artifacts.flatMap((artifact, index) => {
      const fileId = typeof artifact.file_id === 'string' ? artifact.file_id : '';
      if (!fileId) return [];
      return [
        {
          fileId,
          name: typeof artifact.name === 'string' ? artifact.name : `产出文件 ${index + 1}`
        }
      ];
    })
  );
}

function BatchOutputCard({ batch }: { batch: WorkflowBatchRead }): React.JSX.Element {
  const outputs = batchOutputFiles(batch);
  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>批次产出</CardTitle>
        <CardDescription>
          批次完成后提供整合核销日清，以及最终的年度盈亏核算表和到账流转表。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {outputs.length ? (
          <PaginatedCollection ariaLabel='批次产出' contentClassName='space-y-2'>
              {outputs.map((output) => (
                <div
                  key={output.fileId}
                  className='flex min-h-10 items-center justify-between gap-3 rounded-md border px-3 py-2'
                >
                  <div className='min-w-0'>
                    <p className='truncate text-sm font-medium'>{output.name}</p>
                  </div>
                  <a
                    href={`/api/platform/files/${encodeURIComponent(output.fileId)}/download`}
                    className='shrink-0 text-sm text-primary underline-offset-4 hover:underline'
                  >
                    下载
                  </a>
                </div>
              ))}
          </PaginatedCollection>
        ) : (
          <p className='text-sm text-muted-foreground'>当前批次还没有可下载的产出文件。</p>
        )}
      </CardContent>
    </Card>
  );
}

export function WorkflowBatchProgress({
  initialBatch
}: WorkflowBatchProgressProps): React.JSX.Element {
  const [batch, setBatch] = React.useState(initialBatch);
  const [selectedWorkflowId, setSelectedWorkflowId] = React.useState<string | null>(null);
  const [manualSelection, setManualSelection] = React.useState(false);
  const [error, setError] = React.useState('');
  const [refreshing, setRefreshing] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [retrying, setRetrying] = React.useState(false);
  const [fetchedDataOpen, setFetchedDataOpen] = React.useState(false);

  const preferred = React.useMemo(() => preferredWorkflowForBatch(batch), [batch]);
  const current = React.useMemo(() => currentWorkflowForBatch(batch), [batch]);
  const failureGuidance = React.useMemo(() => batchFailureGuidance(batch), [batch]);
  const selectedWorkflow = React.useMemo(
    () => batch.workflows.find((workflow) => workflow.id === selectedWorkflowId) ?? null,
    [batch.workflows, selectedWorkflowId]
  );

  React.useEffect(() => {
    if (selectedWorkflow) {
      if (!manualSelection && preferred && selectedWorkflow.id !== preferred.id) {
        setSelectedWorkflowId(preferred.id);
      }
      return;
    }
    setSelectedWorkflowId(preferred?.id ?? null);
    setManualSelection(false);
  }, [manualSelection, preferred, selectedWorkflow, selectedWorkflowId]);

  const batchIsTerminal = terminal(batch);

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
    if (batchIsTerminal) return;
    const timer = window.setInterval(() => void refresh(true), 2500);
    return () => window.clearInterval(timer);
  }, [batchIsTerminal, refresh]);

  const writeInProgress = batch.workflows.some((workflow) => workflow.stage === 'applying');

  const cancelBatch = React.useCallback(async () => {
    if (
      terminal(batch) ||
      writeInProgress ||
      !window.confirm('确认取消整个批次吗？未开始的日期不会继续运行，当前原子动作不会被中途截断。')
    ) {
      return;
    }
    setCancelling(true);
    setError('');
    try {
      const response = await fetch(
        `/api/platform/workflow-batches/${encodeURIComponent(batch.id)}/cancel`,
        { method: 'POST' }
      );
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(body?.detail || '批次取消失败。');
      }
      setBatch((await response.json()) as WorkflowBatchRead);
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : '批次取消失败。');
    } finally {
      setCancelling(false);
    }
  }, [batch, writeInProgress]);

  const retryFailedDate = React.useCallback(async () => {
    if (retrying || !batch.can_retry || batch.state !== 'failed') return;
    setRetrying(true);
    setError('');
    try {
      const response = await fetch(
        `/api/platform/workflow-batches/${encodeURIComponent(batch.id)}/retry`,
        { method: 'POST' }
      );
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(body?.detail || '暂时不能重试失败日期。');
      }
      setBatch((await response.json()) as WorkflowBatchRead);
      setError('');
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : '暂时不能重试失败日期。');
    } finally {
      setRetrying(false);
    }
  }, [batch.can_retry, batch.id, batch.state, retrying]);

  const selectedIndex = selectedWorkflow
    ? batch.workflows.findIndex((workflow) => workflow.id === selectedWorkflow.id)
    : -1;
  const selectedStatus = selectedWorkflow ? workflowStatusLabel(selectedWorkflow) : '';
  return (
    <div className='space-y-4'>
      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-start justify-between gap-3'>
            <div>
              <CardTitle>{batch.skill_name}</CardTitle>
              <CardDescription className='mt-1'>
                {batch.display_id} · 已选择 {batch.reconciliation_dates.length}{' '}
                个核销日，按日期顺序处理
              </CardDescription>
            </div>
            <div className='flex flex-wrap items-center justify-end gap-2'>
              <Badge variant='outline' className={statusClass(batchStatusLabel(batch))}>
                {batchStatusLabel(batch)}
              </Badge>
              <Badge variant='secondary'>{batch.progress}%</Badge>
              {!terminal(batch) && (
                <Button
                  type='button'
                  variant='destructive'
                  size='sm'
                  onClick={() => void cancelBatch()}
                  disabled={cancelling || writeInProgress}
                >
                  {cancelling
                    ? '正在取消…'
                    : writeInProgress
                      ? '正在写入，不能取消'
                      : '取消整个批次'}
                </Button>
              )}
            </div>
          </div>
          <Progress
            value={batch.progress}
            aria-label={`批次进度 ${batch.progress}%`}
            className='mt-3'
          />
          <p className='text-sm text-muted-foreground'>{batch.progress_message}</p>
        </CardHeader>
      </Card>

      {batch.fetched_data_available && (
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>本批次智云取数</CardTitle>
            <CardDescription>
              取数范围：{batch.reconciliation_dates[0]} 至 {batch.reconciliation_dates.at(-1)}；
              仅处理已选：{batch.reconciliation_dates.join('、')}
              。取数和检查一次，各已选日期按顺序处理。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              type='button'
              variant='default'
              className={
                batch.fetched_data_review_status === 'confirmed'
                  ? 'bg-primary text-primary-foreground shadow-sm hover:bg-primary/90'
                  : 'bg-amber-600 text-white shadow-sm hover:bg-amber-700'
              }
              onClick={() => setFetchedDataOpen(true)}
            >
              {batch.fetched_data_review_status === 'confirmed'
                ? '查看批次取数数据'
                : '检查批次取数数据'}
            </Button>
          </CardContent>
        </Card>
      )}

      {failureGuidance && (
        <Alert variant='destructive'>
          <AlertTitle>
            {failureGuidance.failedDate} 在“{failureGuidance.failedStep}”未完成
          </AlertTitle>
          <AlertDescription className='space-y-3'>
            <p>{failureGuidance.laterDatesMessage}</p>
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <span>{failureGuidance.nextAction}</span>
              {batch.can_retry && (
                <Button
                  type='button'
                  variant='destructive'
                  onClick={() => void retryFailedDate()}
                  disabled={retrying}
                >
                  {retrying
                    ? '正在重新执行…'
                    : (batch.retry_message ?? '').includes('范围报告')
                      ? '重新生成范围报告'
                      : '重试失败日期'}
                </Button>
              )}
            </div>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className='text-base'>日期任务</CardTitle>
        </CardHeader>
        <CardContent className='space-y-2'>
          <PaginatedCollection ariaLabel='批次日期任务列表' contentClassName='space-y-2'>
              {batch.workflows.map((workflow) => {
                const status = workflowStatusInBatch(batch.state, batch.workflows, workflow);
                const selected = selectedWorkflow?.id === workflow.id;
                const currentTask = current?.id === workflow.id;
                const hint = workflowAttentionHint(workflow);
                return (
                  <div
                    key={workflow.id}
                    role='listitem'
                    data-workflow-selected={selected}
                    className={`rounded-lg border border-l-4 p-3 transition-colors ${
                      selected
                        ? 'border-l-primary bg-primary/10 shadow-sm dark:bg-primary/15'
                        : currentTask
                          ? 'border-l-primary/60 bg-primary/5'
                          : 'border-l-transparent'
                    }`}
                  >
                    <button
                      type='button'
                      className='w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
                      aria-pressed={selected}
                      onClick={() => {
                        setSelectedWorkflowId(workflow.id);
                        setManualSelection(true);
                      }}
                    >
                      <div className='flex flex-wrap items-center gap-x-3 gap-y-2'>
                        <span className='font-medium'>第 {workflow.batch_sequence} 天</span>
                        <span className='text-sm'>{workflow.reconciliation_date}</span>
                        <Badge variant='outline' className={statusClass(status)}>
                          {status}
                        </Badge>
                        <span className='min-w-36 text-sm text-muted-foreground'>
                          {workflowStepLabel(workflow)}
                        </span>
                        <span className='ml-auto text-sm font-medium tabular-nums'>
                          {workflow.progress}%
                        </span>
                      </div>
                      <div className='mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground'>
                        {currentTask && <span className='font-medium text-primary'>当前执行</span>}
                        {selected && <span className='font-medium text-foreground'>当前查看</span>}
                        {hint && (
                          <span
                            className={
                              status === '失败'
                                ? 'text-destructive'
                                : 'text-amber-700 dark:text-amber-300'
                            }
                            title={hint}
                          >
                            {hint}
                          </span>
                        )}
                        <span className='truncate'>任务号：{workflow.display_id}</span>
                      </div>
                    </button>
                  </div>
                );
              })}
          </PaginatedCollection>
        </CardContent>
      </Card>

      {selectedWorkflow && (
        <div data-testid='selected-workflow-detail' className='space-y-3'>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <div>
              <p className='font-medium'>
                当前查看：{selectedWorkflow.reconciliation_date}（第 {selectedIndex + 1}/
                {batch.workflows.length} 天）
              </p>
              <p className='text-sm text-muted-foreground'>状态：{selectedStatus}</p>
            </div>
            {preferred && selectedWorkflow.id !== preferred.id && (
              <Button
                type='button'
                variant='outline'
                size='sm'
                onClick={() => {
                  setSelectedWorkflowId(preferred.id);
                  setManualSelection(false);
                }}
              >
                {batch.state === 'failed'
                  ? '返回失败日期'
                  : batchIsTerminal
                    ? '返回默认日期'
                    : '返回当前任务'}
              </Button>
            )}
          </div>

          {batchIsTerminal && !isTerminalWorkflow(selectedWorkflow) ? (
            <Card>
              <CardContent className='py-6'>
                <p className='font-medium'>
                  {batch.state === 'failed'
                    ? '批次已在前一失败日期停止，这一天尚未开始。'
                    : batch.state === 'cancelled'
                      ? '批次已取消，这一天不会继续执行。'
                      : '批次已经完成，这一天不再继续执行。'}
                </p>
              </CardContent>
            </Card>
          ) : isWaitingWorkflow(selectedWorkflow) ? (
            <Card>
              <CardContent className='py-6'>
                <p className='font-medium'>这一天正在等待前置日期完成。</p>
              </CardContent>
            </Card>
          ) : (
            <>
              <WorkflowProgressCard
                workflow={selectedWorkflow}
                onOpenFetchedData={() => setFetchedDataOpen(true)}
              />
              {(selectedWorkflow.state === 'succeeded' ||
                selectedWorkflow.stage === 'completed') && (
                <Card>
                  <CardHeader>
                    <CardTitle className='text-base'>本日期核销结果</CardTitle>
                    <CardDescription>
                      {selectedWorkflow.reconciliation_date} · 写入状态：已完成
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PaginatedCollection
                      ariaLabel='本日期核销结果'
                      contentClassName='grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4'
                    >
                      {[
                      ['本日写入', '今天要填'],
                      ['已填过·跳过', '已填过·跳过'],
                      ['挂账待办', '挂账待办'],
                      ['冲突·需人工处理', '冲突·需你定'],
                      ['流转确认后自动写', '流转确认后自动写'],
                      ['流转须手填', '流转须手填'],
                      ['异常', '异常']
                      ].map(([label, key]) => (
                        <div key={key} className='rounded-md border bg-muted/20 p-3'>
                          <p className='text-muted-foreground'>{label}</p>
                          <p className='mt-1 font-medium'>
                            {resultSummaryValue(selectedWorkflow.result_summary ?? {}, key)}
                          </p>
                        </div>
                      ))}
                    </PaginatedCollection>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </div>
      )}

      <BatchOutputCard batch={batch} />

      {error && (
        <p className='text-sm text-destructive' role='alert' aria-live='assertive'>
          {error}
        </p>
      )}
      <p className='sr-only' aria-live='polite'>
        {batch.state === 'running' && batch.progress_message}
      </p>
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
          nativeButton={false}
          variant='default'
          className='shadow-sm'
          render={<Link href='/dashboard/runs' aria-label='返回任务列表' />}
        >
          返回任务列表
        </Button>
      </div>
      <WorkflowFetchedDataDialog
        batch={batch}
        open={fetchedDataOpen}
        reconciliationDate={selectedWorkflow?.reconciliation_date}
        onOpenChange={setFetchedDataOpen}
        onBatchChange={setBatch}
      />
    </div>
  );
}
