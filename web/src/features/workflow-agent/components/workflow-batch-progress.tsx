'use client';

import * as React from 'react';
import { isArSkill } from '@/features/workflow-agent/ar-skill-identity';
import Link from 'next/link';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import { Progress } from '@/components/ui/progress';
import { Heading } from '@/components/ui/heading';
import { WorkflowProgressCard } from '@/features/workflow-agent/components/workflow-progress-card';
import { WorkflowFetchedDataDialog } from '@/features/workflow-agent/components/workflow-fetched-data-dialog';
import { WorkflowResultSummary } from '@/features/workflow-agent/components/workflow-result-summary';
import { WorkflowRecoveryActions } from '@/features/workflow-agent/components/workflow-execution-results';
import { useWorkflowPolling } from '@/features/workflow-agent/hooks/use-workflow-polling';
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
        <CardTitle className='text-base'><h2>批次产出</h2></CardTitle>
      </CardHeader>
      <CardContent>
        {outputs.length ? (
          <PaginatedCollection ariaLabel='批次产出' contentClassName='platform-list'>
              {outputs.map((output) => (
                <div
                  key={output.fileId}
                  className='platform-row'
                >
                  <div className='min-w-0'>
                    <p className='text-sm font-medium break-words'>{output.name}</p>
                  </div>
                  <a
                    href={`/api/platform/files/${encodeURIComponent(output.fileId)}/download`}
                    className='platform-action shrink-0 text-sm text-primary underline-offset-4 hover:underline'
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

function DateTaskList({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      role='list'
      aria-label='批次日期任务列表'
      tabIndex={0}
      className='platform-date-task-list flex flex-col gap-2 overflow-y-auto overscroll-contain rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&>*]:shrink-0'
      style={{ scrollbarGutter: 'stable' }}
    >
      {children}
    </div>
  );
}

export function WorkflowBatchProgress({
  initialBatch
}: WorkflowBatchProgressProps): React.JSX.Element {
  const [batch, setBatch] = React.useState(initialBatch);
  const [selectedWorkflowId, setSelectedWorkflowId] = React.useState<string | null>(() => preferredWorkflowForBatch(initialBatch)?.id ?? null);
  const [resultWorkflowId, setResultWorkflowId] = React.useState('');
  const resultWorkflow = batch.workflows.find(workflow => workflow.id === resultWorkflowId);
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

  useWorkflowPolling({
    enabled: !batchIsTerminal,
    fast:
      batch.state === 'running' ||
      batch.workflows.some((workflow) =>
        ['preparing', 'fetching_data', 'building_fetch_preview', 'applying', 'finalizing'].includes(
          workflow.stage
        )
      ),
    refresh: () => refresh(true)
  });

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
    <div className='space-y-6'>
      <div className='flex flex-wrap items-start justify-between gap-4'>
        <Heading title='应收核销批次详情' description='' level={1} compact />
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
            variant='outline'
            render={<Link href='/dashboard/runs' aria-label='返回任务列表' />}
          >
            返回任务列表
          </Button>
        </div>
      </div>
      <Card>
        <CardHeader>
          <div className='flex flex-wrap items-start justify-between gap-3'>
            <div>
              <CardTitle><h2>{batch.skill_name}</h2></CardTitle>
              <CardDescription className='mt-1'>
                {batch.display_id} · {batch.reconciliation_dates.length} 个核销日
              </CardDescription>
            </div>
            <div className='flex flex-wrap items-center justify-end gap-2'>
              <Badge variant='outline' className={statusClass(batchStatusLabel(batch))}>
                {batchStatusLabel(batch)}
              </Badge>
              <Badge variant='secondary'>{batch.progress}%</Badge>
              {batch.fetched_data_available && (
                <Button
                  type='button'
                  variant='default'
                  className={
                    (isArSkill(batch.skill_id) || batch.fetched_data_review_status === 'confirmed')
                      ? 'bg-primary text-primary-foreground shadow-sm hover:bg-primary/90'
                      : 'bg-amber-600 text-white shadow-sm hover:bg-amber-700'
                  }
                  onClick={() => setFetchedDataOpen(true)}
                >
                  {(isArSkill(batch.skill_id) || batch.fetched_data_review_status === 'confirmed')
                    ? '查看本次取数'
                    : '检查批次取数数据'}
                </Button>
              )}
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

      {failureGuidance && (
        <Alert variant='destructive'>
          <AlertTitle>
            {failureGuidance.failedDate} 在“{failureGuidance.failedStep}”未完成
          </AlertTitle>
          <AlertDescription className='space-y-3'>
            {failureGuidance.laterDatesMessage !== '没有后续未处理日期。' && (
              <p>{failureGuidance.laterDatesMessage}</p>
            )}
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

      <div className='platform-batch-grid'>
        <Card className='platform-date-task-card'>
          <CardHeader>
            <CardTitle className='text-base'><h2>日期任务</h2></CardTitle>
          </CardHeader>
          <CardContent className='platform-date-task-content'>
            <DateTaskList>
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
                        className='min-h-11 w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
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
                          <span className='text-sm text-muted-foreground'>
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
                          <span className='break-all'>任务号：{workflow.display_id}</span>
                        </div>
                      </button>
                    </div>
                  );
                })}
            </DateTaskList>
          </CardContent>
        </Card>

        {selectedWorkflow && (
          <div data-testid='selected-workflow-detail' className='space-y-3'>
            <div className='flex flex-wrap items-center justify-between gap-3'>
              <div>
                <h2 className='font-medium'>
                  当前查看：{selectedWorkflow.reconciliation_date}（第 {selectedIndex + 1}/
                  {batch.workflows.length} 天）
                </h2>
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

            <WorkflowProgressCard
              compact
              workflow={selectedWorkflow}
              waitingMessage={
                selectedWorkflow.state === 'cancelled'
                  ? '这一天已取消，不会继续执行。'
                  : batchIsTerminal && !isTerminalWorkflow(selectedWorkflow)
                  ? batch.state === 'failed'
                    ? '批次已在前一失败日期停止，这一天尚未开始。'
                    : batch.state === 'cancelled'
                      ? '批次已取消，这一天不会继续执行。'
                      : '批次已经完成，这一天不再继续执行。'
                  : isWaitingWorkflow(selectedWorkflow)
                    ? selectedWorkflow.batch_sequence > 1
                      ? '这一天正在等待前置日期完成。'
                      : '这一天尚未开始，正在等待执行。'
                    : undefined
              }
              onOpenFetchedData={() => setFetchedDataOpen(true)}
            />
            {selectedWorkflow.state === 'failed' && (
              <WorkflowRecoveryActions key={selectedWorkflow.id} workflow={selectedWorkflow} onRecovered={() => refresh()} />
            )}
          </div>
        )}

      </div>

      <WorkflowResultSummary
        key={resultWorkflow?.id ?? batch.id}
        source={resultWorkflow ?? batch}
        title='本批次核销结果'
        emptyMessage={resultWorkflow ? '这一天尚无可展示的核销结果。' : '本批次尚无可展示的汇总结果，可选择具体日期查看。'}
        controls={
          <label className='flex flex-wrap items-center gap-2 text-sm'>
            <span>结果范围</span>
            <select
              aria-label='核销结果日期'
              value={resultWorkflow?.id ?? ''}
              onChange={event => setResultWorkflowId(event.target.value)}
              className='min-h-11 max-w-full rounded-md border bg-background px-3 text-foreground'
            >
              <option value=''>全部日期（汇总）</option>
              {batch.workflows.map(workflow => <option key={workflow.id} value={workflow.id}>
                {workflow.reconciliation_date}（第 {workflow.batch_sequence} 天）
              </option>)}
            </select>
          </label>
        }
      />

      <BatchOutputCard batch={batch} />

      {error && (
        <p className='text-sm text-destructive' role='alert' aria-live='assertive'>
          {error}
        </p>
      )}
      <p className='sr-only' aria-live='polite'>
        {batch.state === 'running' && batch.progress_message}
      </p>
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
