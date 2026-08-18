'use client';

import * as React from 'react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Icons } from '@/components/icons';
import { WorkflowProgressCard } from '@/features/workflow-agent/components/workflow-progress-card';
import type { WorkflowRead } from '@/features/platform-api/types';

interface WorkflowAgentPanelProps {
  initialWorkflow: WorkflowRead;
}

type BindingEntry = { file_id?: unknown; name?: unknown };

const MATERIAL_ROLES = [
  {
    role: 'profit_loss_ledgers',
    label: '年度盈亏核算表',
    description: '可上传多个年度，每个年度保留一份。'
  },
  {
    role: 'receipt_flow_table',
    label: '到账流转表',
    description: '只保留一份；上传新表会替换当前绑定。'
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
  const [workflow, setWorkflow] = React.useState(initialWorkflow);
  const [error, setError] = React.useState('');
  const [activity, setActivity] = React.useState('');
  const [confirmationBusy, setConfirmationBusy] = React.useState(false);
  const [uploadingRole, setUploadingRole] = React.useState('');
  const [refreshing, setRefreshing] = React.useState(false);
  const filesEditable = ['awaiting_files', 'failed'].includes(workflow.stage);

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

  React.useEffect(() => {
    if (isTerminal(workflow)) return;
    const timer = window.setInterval(() => void refresh(true), 2000);
    return () => window.clearInterval(timer);
  }, [refresh, workflow]);

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
      setActivity('已提交确认，后台任务将继续执行写入。');
    } catch (confirmError) {
      setError(confirmError instanceof Error ? confirmError.message : '确认写入失败。');
    } finally {
      setConfirmationBusy(false);
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
      if (!response.ok) throw new Error(await responseMessage(response, '重新生成失败。'));
      setWorkflow((await response.json()) as WorkflowRead);
      setActivity('已重新排队，后台会从当前日期重新生成日清。');
    } catch (rebuildError) {
      setError(rebuildError instanceof Error ? rebuildError.message : '重新生成失败。');
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
          body: JSON.stringify({ files: { [role]: nextIds } })
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

  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div>
          <h1 className='text-xl font-semibold'>{workflow.skill_name}</h1>
          <p className='mt-1 text-sm text-muted-foreground'>
            后台任务 · {workflow.reconciliation_date}
          </p>
        </div>
        <Badge variant={workflow.state === 'failed' ? 'destructive' : 'secondary'}>
          {workflow.state === 'succeeded' ? '已完成' : workflow.stage}
        </Badge>
      </div>

      <WorkflowProgressCard workflow={workflow} />

      {workflow.stage === 'awaiting_apply_confirmation' && (
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

      {workflow.state === 'failed' && (
        <Alert variant='destructive'>
          <AlertTitle>任务没有完成</AlertTitle>
          <AlertDescription className='flex flex-wrap items-center justify-between gap-3'>
            <span>请先查看上方流程卡片标出的失败步骤，再决定是否重新生成。</span>
            <Button
              type='button'
              variant='destructive'
              onClick={() => void rebuild()}
              disabled={confirmationBusy}
            >
              {confirmationBusy ? '处理中…' : '重新生成'}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className='text-base'>任务材料</CardTitle>
          <CardDescription>
            首次上传后后续任务会复用；只有需要增加年度表或替换流转表时才需要上传。
          </CardDescription>
        </CardHeader>
        <CardContent className='space-y-3'>
          {MATERIAL_ROLES.map((item) => {
            const entries = bindingEntries(workflow, item.role);
            return (
              <div key={item.role} className='rounded-md border p-3'>
                <div className='flex flex-wrap items-start justify-between gap-2'>
                  <div>
                    <p className='text-sm font-medium'>{item.label}</p>
                    <p className='text-xs text-muted-foreground'>{item.description}</p>
                  </div>
                  {filesEditable && (
                    <label className='cursor-pointer rounded-md border px-3 py-2 text-xs font-medium transition-colors hover:bg-muted'>
                      {uploadingRole === item.role ? '上传中…' : '上传新表'}
                      <input
                        type='file'
                        className='sr-only'
                        accept='.xlsx,.xlsm,.xls'
                        multiple={item.role === 'profit_loss_ledgers'}
                        disabled={Boolean(uploadingRole)}
                        onChange={(event) => void uploadMaterial(item.role, event)}
                      />
                    </label>
                  )}
                </div>
                {entries.length ? (
                  <div className='mt-2 space-y-1 text-xs text-muted-foreground'>
                    {entries.map((entry, index) => (
                      <p key={`${String(entry.file_id)}-${index}`} className='truncate'>
                        {typeof entry.name === 'string' ? entry.name : '已绑定文件'}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className='mt-2 text-xs text-muted-foreground'>
                    尚未上传，将尝试复用历史材料。
                  </p>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>

      {workflow.artifacts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>任务产出</CardTitle>
            <CardDescription>只显示本次任务生成的文件。</CardDescription>
          </CardHeader>
          <CardContent className='space-y-2'>
            {workflow.artifacts.map((artifact, index) => {
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
