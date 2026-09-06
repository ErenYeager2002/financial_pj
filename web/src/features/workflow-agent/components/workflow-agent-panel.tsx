'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import { Icons } from '@/components/icons';
import { WorkflowFetchedDataDialog } from '@/features/workflow-agent/components/workflow-fetched-data-dialog';
import { useWorkflowPolling } from '@/features/workflow-agent/hooks/use-workflow-polling';
import { WorkflowMaterialHistory } from '@/features/workflow-agent/components/workflow-material-history';
import { WorkflowProgressCard } from '@/features/workflow-agent/components/workflow-progress-card';
import { WorkflowRecoveryActions } from '@/features/workflow-agent/components/workflow-execution-results';
import { WorkflowResultSummary } from '@/features/workflow-agent/components/workflow-result-summary';
import { workflowStatusLabel } from '@/features/workflow-agent/workflow-batch-selection';
import type { WorkflowBatchRead, WorkflowRead } from '@/features/platform-api/types';

interface WorkflowAgentPanelProps {
  initialWorkflow: WorkflowRead;
}

type BindingEntry = {
  file_id?: unknown;
  name?: unknown;
  year?: unknown;
  sha256?: unknown;
  source_workflow_id?: unknown;
  published_at?: unknown;
};

const MATERIAL_ROLES = [
  {
    role: 'profit_loss_ledgers',
    label: '年度盈亏核算表（每年一份）'
  },
  {
    role: 'receipt_flow_table',
    label: '到账流转表'
  }
] as const;

function responseMessage(response: Response, fallback: string): Promise<string> {
  return response
    .json()
    .then((body: unknown) => {
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        return body.detail;
      }
      return fallback;
    })
    .catch(() => fallback);
}

function bindingEntries(workflow: WorkflowRead, role: string): BindingEntry[] {
  const direct = workflow.files?.[role];
  if (Array.isArray(direct)) {
    return direct.filter((item): item is BindingEntry => {
      return typeof item === 'object' && item !== null && !Array.isArray(item);
    });
  }
  const legacy = workflow.files?.finance_workbooks;
  if (!Array.isArray(legacy)) return [];
  return legacy.filter((item): item is BindingEntry => {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) return false;
    const rawName = (item as BindingEntry).name;
    const name = typeof rawName === 'string' ? rawName.toLowerCase() : '';
    const isFlow = name.includes('到账') || name.includes('流转') || name.includes('flow');
    return role === 'receipt_flow_table' ? isFlow : !isFlow;
  });
}

function bindingIds(workflow: WorkflowRead, role: string): string[] {
  return bindingEntries(workflow, role)
    .map((item) => (typeof item.file_id === 'string' ? item.file_id : ''))
    .filter(Boolean);
}

function isTerminal(workflow: WorkflowRead): boolean {
  return ['succeeded', 'failed', 'cancelled'].includes(workflow.state);
}

export function WorkflowAgentPanel({
  initialWorkflow
}: WorkflowAgentPanelProps): React.JSX.Element {
  const router = useRouter();
  const [workflow, setWorkflow] = React.useState(initialWorkflow);
  const [error, setError] = React.useState('');
  const [activity, setActivity] = React.useState('');
  const [confirmationBusy, setConfirmationBusy] = React.useState(false);
  const [uploadingRole, setUploadingRole] = React.useState('');
  const [deletingFileId, setDeletingFileId] = React.useState('');
  const [refreshing, setRefreshing] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [fetchedDataOpen, setFetchedDataOpen] = React.useState(false);
  const writeInProgress = workflow.stage === 'applying';
  const filesEditable = ['awaiting_date', 'awaiting_date_confirmation', 'awaiting_files'].includes(
    workflow.stage
  );

  const refresh = React.useCallback(
    async (silent = false) => {
      if (!silent) setRefreshing(true);
      try {
        const response = await fetch(`/api/platform/workflows/${encodeURIComponent(workflow.id)}`, {
          cache: 'no-store'
        });
        if (!response.ok) throw new Error(await responseMessage(response, '任务状态加载失败。'));
        setWorkflow((await response.json()) as WorkflowRead);
      } catch (refreshError) {
        if (!silent) {
          setError(refreshError instanceof Error ? refreshError.message : '任务状态加载失败。');
        }
      } finally {
        if (!silent) setRefreshing(false);
      }
    },
    [workflow.id]
  );

  useWorkflowPolling({
    enabled: !isTerminal(workflow),
    fast: ['preparing', 'fetching_data', 'building_fetch_preview', 'applying', 'finalizing'].includes(
      workflow.stage
    ),
    refresh: () => refresh(true)
  });

  async function confirmWrite() {
    if (confirmationBusy) return;
    setConfirmationBusy(true);
    setError('');
    try {
      const response = await fetch(
        `/api/platform/workflows/${encodeURIComponent(workflow.id)}/confirm`,
        { method: 'POST' }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '确认写入失败。'));
      setWorkflow((await response.json()) as WorkflowRead);
      setActivity('已提交确认，任务将继续执行写入。');
    } catch (confirmError) {
      setError(confirmError instanceof Error ? confirmError.message : '确认写入失败。');
    } finally {
      setConfirmationBusy(false);
    }
  }

  async function cancelTask() {
    if (cancelling || isTerminal(workflow) || writeInProgress) return;
    const cancellingBatch = Boolean(workflow.batch_id);
    const prompt = cancellingBatch
      ? '该任务属于多日期批次。确认取消整个批次吗？未开始的日期不会继续运行，当前原子动作不会被中途截断。'
      : '确认取消当前任务吗？尚未开始的动作不会执行；正在运行的取数动作结束后停止。';
    if (!window.confirm(prompt)) return;
    setCancelling(true);
    setError('');
    try {
      const endpoint = cancellingBatch
        ? `/api/platform/workflow-batches/${encodeURIComponent(workflow.batch_id as string)}/cancel`
        : `/api/platform/workflows/${encodeURIComponent(workflow.id)}/cancel`;
      const response = await fetch(endpoint, { method: 'POST' });
      if (!response.ok) throw new Error(await responseMessage(response, '取消任务失败。'));
      if (cancellingBatch) {
        const batch = (await response.json()) as WorkflowBatchRead;
        const current = batch.workflows.find((item) => item.id === workflow.id);
        if (current) setWorkflow(current);
        setActivity(
          batch.state === 'cancelled'
            ? '整个批次已取消。'
            : '已申请取消整个批次，当前原子动作结束后停止。'
        );
      } else {
        const nextWorkflow = (await response.json()) as WorkflowRead;
        setWorkflow(nextWorkflow);
        setActivity(
          nextWorkflow.state === 'cancelled'
            ? '任务已取消。'
            : '已申请取消，当前取数动作结束后停止。'
        );
      }
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : '取消任务失败。');
    } finally {
      setCancelling(false);
    }
  }

  async function rebuild() {
    if (confirmationBusy) return;
    setConfirmationBusy(true);
    setError('');
    try {
      const response = await fetch(
        `/api/platform/workflows/${encodeURIComponent(workflow.id)}/rebuild`,
        { method: 'POST' }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '新建任务失败。'));
      const nextWorkflow = (await response.json()) as WorkflowRead;
      setWorkflow(nextWorkflow);
      router.replace(`/dashboard/workflows/${encodeURIComponent(nextWorkflow.id)}`);
      setActivity('已创建新任务，将使用当前业务材料版本并重新取数。');
    } catch (rebuildError) {
      setError(rebuildError instanceof Error ? rebuildError.message : '新建任务失败。');
    } finally {
      setConfirmationBusy(false);
    }
  }

  async function uploadMaterial(
    role: (typeof MATERIAL_ROLES)[number]['role'],
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const selected = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (!selected.length || uploadingRole) return;
    const uploads = role === 'receipt_flow_table' ? selected.slice(0, 1) : selected;
    setUploadingRole(role);
    setError('');
    try {
      const uploadedIds: string[] = [];
      for (const upload of uploads) {
        const form = new FormData();
        form.set('skill_id', workflow.skill_id);
        form.set('workflow_id', workflow.id);
        form.set('role', role);
        form.set('upload', upload);
        const response = await fetch('/api/platform/files', { method: 'POST', body: form });
        if (!response.ok) throw new Error(await responseMessage(response, '文件上传失败。'));
        const result = (await response.json()) as { id?: unknown };
        if (typeof result.id !== 'string') throw new Error('文件上传结果无效。');
        uploadedIds.push(result.id);
      }
      const currentIds = bindingIds(workflow, role);
      const nextIds =
        role === 'receipt_flow_table'
          ? uploadedIds
          : [...currentIds, ...uploadedIds.filter((id) => !currentIds.includes(id))];
      const response = await fetch(
        `/api/platform/workflows/${encodeURIComponent(workflow.id)}/files`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { [role]: nextIds }, replace_roles: [role] })
        }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '文件绑定失败。'));
      setWorkflow((await response.json()) as WorkflowRead);
      setActivity(`已更新${role === 'receipt_flow_table' ? '到账流转表' : '年度盈亏核算表'}。`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : '文件上传失败。');
    } finally {
      setUploadingRole('');
    }
  }

  async function removeMaterial(
    role: (typeof MATERIAL_ROLES)[number]['role'],
    fileId: string,
    fileName: string
  ) {
    if (!filesEditable || deletingFileId || uploadingRole) return;
    if (!window.confirm(`确认从本次任务中移除“${fileName}”吗？`)) return;
    setDeletingFileId(fileId);
    setError('');
    try {
      const nextIds = bindingIds(workflow, role).filter((id) => id !== fileId);
      const response = await fetch(
        `/api/platform/workflows/${encodeURIComponent(workflow.id)}/files`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: { [role]: nextIds }, replace_roles: [role] })
        }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '文件移除失败。'));
      setWorkflow((await response.json()) as WorkflowRead);
      setActivity(
        `已从本次任务移除${role === 'receipt_flow_table' ? '到账流转表' : '年度盈亏核算表'}：${fileName}`
      );
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : '文件移除失败。');
    } finally {
      setDeletingFileId('');
    }
  }

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div>
          {workflow.batch_id && (
            <Link
              href={`/dashboard/workflows/batches/${encodeURIComponent(workflow.batch_id)}`}
              className='mb-2 inline-flex items-center rounded-md border border-primary/40 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10'
            >
              返回所属批次
            </Link>
          )}
          <h1 className='text-xl font-semibold'>{workflow.skill_name}</h1>
          <p className='mt-1 text-sm text-muted-foreground'>
            {workflow.display_id} · {workflow.reconciliation_date}
          </p>
        </div>
        <div className='flex flex-wrap items-center gap-2'>
          <Badge
            variant={workflow.state === 'failed' ? 'destructive' : 'secondary'}
            aria-label={`任务状态：${workflowStatusLabel(workflow)}`}
          >
            {workflowStatusLabel(workflow)}
          </Badge>
          {!isTerminal(workflow) && (
            <Button
              type='button'
              variant='destructive'
              size='sm'
              disabled={cancelling || workflow.state === 'cancelling' || writeInProgress}
              onClick={() => void cancelTask()}
            >
              {writeInProgress
                ? '正在写入，不能取消'
                : cancelling || workflow.state === 'cancelling'
                  ? '正在取消…'
                  : workflow.batch_id
                    ? '取消整个批次'
                    : '取消任务'}
            </Button>
          )}
        </div>
      </div>

      <WorkflowProgressCard
        workflow={workflow}
        onOpenFetchedData={() => setFetchedDataOpen(true)}
      />
      {workflow.fetched_data_available && isTerminal(workflow) && (
        <div className='flex justify-end'>
          <Button type='button' variant='outline' onClick={() => setFetchedDataOpen(true)}>
            查看已保存的取数数据
          </Button>
        </div>
      )}
      <WorkflowFetchedDataDialog
        workflow={workflow}
        open={fetchedDataOpen}
        onOpenChange={setFetchedDataOpen}
        onWorkflowChange={setWorkflow}
      />

      {workflow.stage === 'awaiting_fetched_data_confirmation' && (
        <Alert>
          <AlertTitle>请检查智云取数数据</AlertTitle>
          <AlertDescription className='flex flex-wrap items-center justify-between gap-3'>
            <span>确认数据后继续核销。</span>
            <Button type='button' onClick={() => setFetchedDataOpen(true)}>
              检查并确认
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {workflow.stage === 'awaiting_apply_confirmation' &&
        workflow.skill_id !== 'ar-hexiao-daily' && (
          <Alert>
            <AlertTitle>核销日清已经生成</AlertTitle>
            <AlertDescription className='flex flex-wrap items-center justify-between gap-3'>
              <span>请检查产出文件；确认后会写入工作副本。</span>
              <Button type='button' onClick={() => void confirmWrite()} disabled={confirmationBusy}>
                {confirmationBusy ? '处理中…' : '确认写入'}
              </Button>
            </AlertDescription>
          </Alert>
        )}

      {(workflow.stage === 'waiting_approval' || workflow.state === 'waiting_approval') && (
        <Alert>
          <AlertTitle>等待管理员审批</AlertTitle>
          <AlertDescription>
            由另一名管理员审批后开始写入。
          </AlertDescription>
        </Alert>
      )}

      {workflow.state === 'failed' && (
        <Alert variant='destructive'>
          <AlertTitle>
            任务没有完成
            {workflow.step_error_detail?.error_code
              ? `（${workflow.step_error_detail.error_code}）`
              : ''}
          </AlertTitle>
          <AlertDescription className='flex flex-wrap items-center justify-between gap-3'>
            <span>
              {typeof workflow.step_error_detail?.rebuild_block_reason === 'string'
                ? workflow.step_error_detail.rebuild_block_reason
                : '请先查看上方流程卡片标出的失败步骤及恢复条件，再决定是否新建日清。'}
            </span>
            <Button
              type='button'
              variant='destructive'
              onClick={() => void rebuild()}
              disabled={
                confirmationBusy || workflow.step_error_detail?.recovery_allowed !== true
              }
            >
              {confirmationBusy
                ? '正在创建…'
                : workflow.step_error_detail?.recovery_allowed === true
                  ? '用当前材料版本新建日清'
                  : '恢复条件待核实'}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {workflow.state === 'failed' && (
        <WorkflowRecoveryActions workflow={workflow} onRecovered={refresh} />
      )}
      <WorkflowResultSummary source={workflow} title='本次核销结果' />

      <Card>
        <CardHeader>
          <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
            任务材料
            {workflow.material_version !== null && workflow.material_version !== undefined && (
              <Badge variant='secondary'>业务版本 V{workflow.material_version}</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className='space-y-3'>
          {MATERIAL_ROLES.map((item) => {
            const entries = bindingEntries(workflow, item.role);
            return (
              <div key={item.role} className='rounded-md border p-3'>
                <div className='flex flex-wrap items-start justify-between gap-2'>
                  <div>
                    <p className='text-sm font-medium'>{item.label}</p>
                  </div>
                  {filesEditable && (
                    <label className='cursor-pointer rounded-md border px-3 py-2 text-xs font-medium transition-colors hover:bg-muted'>
                      {uploadingRole === item.role
                        ? '上传中…'
                        : item.role === 'receipt_flow_table' && entries.length > 0
                          ? '替换当前表'
                          : '上传新表'}
                      <input
                        type='file'
                        className='sr-only'
                        accept='.xlsx,.xlsm,.xls'
                        multiple={item.role === 'profit_loss_ledgers'}
                        disabled={Boolean(uploadingRole) || Boolean(deletingFileId)}
                        onChange={(event) => void uploadMaterial(item.role, event)}
                      />
                    </label>
                  )}
                </div>
                {entries.length ? (
                  <PaginatedCollection
                    ariaLabel={`${item.label}任务材料`}
                    className='mt-2'
                    contentClassName='space-y-1 text-xs text-muted-foreground'
                  >
                    {entries.map((entry, index) => (
                      <div
                        key={`${String(entry.file_id)}-${index}`}
                        className='flex items-center gap-2 rounded-md bg-muted/40 px-2 py-1'
                      >
                        <span className='min-w-0 flex-1 truncate'>
                          {typeof entry.name === 'string' ? entry.name : '已绑定文件'}
                        </span>
                        {typeof entry.year === 'number' && (
                          <Badge variant='outline'>{entry.year} 年</Badge>
                        )}
                        {filesEditable && typeof entry.file_id === 'string' && (
                          <Button
                            type='button'
                            variant='ghost'
                            size='icon'
                            className='min-h-11 min-w-11 shrink-0 text-muted-foreground hover:text-destructive'
                            aria-label={`从任务移除 ${typeof entry.name === 'string' ? entry.name : '文件'}`}
                            title='从本次任务移除'
                            disabled={Boolean(uploadingRole) || Boolean(deletingFileId)}
                            onClick={() =>
                              void removeMaterial(
                                item.role,
                                entry.file_id as string,
                                typeof entry.name === 'string' ? entry.name : '文件'
                              )
                            }
                          >
                            {deletingFileId === entry.file_id ? (
                              <Icons.spinner className='size-4 animate-spin' />
                            ) : (
                              <Icons.trash className='size-4' />
                            )}
                          </Button>
                        )}
                      </div>
                    ))}
                  </PaginatedCollection>
                ) : (
                  <p className='mt-2 text-xs text-muted-foreground'>
                    尚未上传，将尝试复用历史材料。
                  </p>
                )}
              </div>
            );
          })}
          <WorkflowMaterialHistory skillId={workflow.skill_id} allowRestore />
        </CardContent>
      </Card>

      {workflow.artifacts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>任务产出</CardTitle>
          </CardHeader>
          <CardContent>
            <PaginatedCollection ariaLabel='任务产出' contentClassName='space-y-2'>
            {[...workflow.artifacts]
              .toSorted((left, right) => {
                const leftName = typeof left.name === 'string' ? left.name : '';
                const rightName = typeof right.name === 'string' ? right.name : '';
                return (
                  Number(!leftName.includes('核销日清')) - Number(!rightName.includes('核销日清'))
                );
              })
              .map((artifact, index) => {
                const fileId = typeof artifact.file_id === 'string' ? artifact.file_id : '';
                const name =
                  typeof artifact.name === 'string' ? artifact.name : `产出文件 ${index + 1}`;
                return fileId ? (
                  <a
                    key={`${fileId}-${index}`}
                    href={`/api/platform/files/${encodeURIComponent(fileId)}/download`}
                    className='flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring'
                  >
                    <Icons.page className='size-4 text-muted-foreground' aria-hidden='true' />
                    {name}
                  </a>
                ) : null;
              })}
            </PaginatedCollection>
          </CardContent>
        </Card>
      )}

      {(activity || error) && (
        <div className='space-y-1' aria-live='polite'>
          {activity && <p className='text-sm text-muted-foreground'>{activity}</p>}
          {error && (
            <p className='text-sm text-destructive' role='alert'>
              {error}
            </p>
          )}
        </div>
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
          nativeButton={false}
          variant='ghost'
          className='border border-primary/40 text-primary hover:bg-primary/10 hover:text-primary'
          render={
            <Link
              href={
                workflow.batch_id
                  ? `/dashboard/workflows/batches/${encodeURIComponent(workflow.batch_id)}`
                  : '/dashboard/runs'
              }
              aria-label={workflow.batch_id ? '返回所属批次' : '返回任务列表'}
            />
          }
        >
          {workflow.batch_id ? '返回所属批次' : '返回任务列表'}
        </Button>
      </div>
    </div>
  );
}
