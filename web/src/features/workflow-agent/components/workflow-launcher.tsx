'use client';

import * as React from 'react';
import Link from 'next/link';
import { format, startOfDay } from 'date-fns';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Icons } from '@/components/icons';
import type { SkillDetail, WorkflowRead } from '@/features/platform-api/types';

interface WorkflowLauncherProps {
  skills: SkillDetail[];
  workflows: WorkflowRead[];
  initialSkillId?: string;
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    awaiting_date: '等待选择日期',
    awaiting_files: '等待材料',
    preparing: '后台处理中',
    awaiting_apply_confirmation: '等待确认写入',
    waiting_approval: '继续执行',
    applying: '写入中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    queued: '排队中'
  };
  return labels[stage] ?? stage;
}

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

export function WorkflowLauncher({
  skills,
  workflows,
  initialSkillId = ''
}: WorkflowLauncherProps): React.JSX.Element {
  const today = React.useMemo(() => startOfDay(new Date()), []);
  const selectedInitialSkill =
    initialSkillId && skills.some((skill) => skill.id === initialSkillId)
      ? initialSkillId
      : (skills[0]?.id ?? '');
  const [skillId, setSkillId] = React.useState(selectedInitialSkill);
  const [selectedDates, setSelectedDates] = React.useState<Date[]>([]);
  const [files, setFiles] = React.useState<Record<string, string[]>>({});
  const [fileNames, setFileNames] = React.useState<Record<string, string[]>>({});
  const [uploadingRole, setUploadingRole] = React.useState('');
  const [working, setWorking] = React.useState(false);
  const [error, setError] = React.useState('');
  const selectedSkill = skills.find((skill) => skill.id === skillId);
  const fileInputs = selectedSkill?.file_inputs ?? [];

  React.useEffect(() => {
    setSelectedDates([]);
    setFiles({});
    setFileNames({});
    setError('');
  }, [skillId]);

  async function uploadMaterial(
    role: string,
    multiple: boolean,
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const selected = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (!selected.length || uploadingRole) return;
    const uploads = multiple ? selected : selected.slice(0, 1);
    setUploadingRole(role);
    setError('');
    try {
      const uploaded: Array<{ id: string; name: string }> = [];
      for (const file of uploads) {
        const form = new FormData();
        form.set('skill_id', skillId);
        form.set('role', role);
        form.set('workflow_upload', 'true');
        form.set('upload', file);
        const response = await fetch('/api/platform/files', { method: 'POST', body: form });
        if (!response.ok) throw new Error(await responseMessage(response, '文件上传失败。'));
        const result = (await response.json()) as { id?: unknown; name?: unknown };
        if (typeof result.id !== 'string') throw new Error('文件上传结果无效。');
        uploaded.push({
          id: result.id,
          name: typeof result.name === 'string' ? result.name : file.name
        });
      }
      setFiles((current) => ({
        ...current,
        [role]: multiple
          ? [...(current[role] ?? []), ...uploaded.map((item) => item.id)]
          : uploaded.map((item) => item.id)
      }));
      setFileNames((current) => ({
        ...current,
        [role]: multiple
          ? [...(current[role] ?? []), ...uploaded.map((item) => item.name)]
          : uploaded.map((item) => item.name)
      }));
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : '文件上传失败。');
    } finally {
      setUploadingRole('');
    }
  }

  async function start() {
    const dates = selectedDates
      .filter((item) => startOfDay(item) <= today)
      .toSorted((left, right) => left.getTime() - right.getTime())
      .map((item) => format(item, 'yyyy-MM-dd'));
    if (!dates.length || !skillId || working || uploadingRole) return;
    setWorking(true);
    setError('');
    try {
      const endpoint =
        dates.length === 1
          ? '/api/platform/workflows/start'
          : '/api/platform/workflow-batches/start';
      const body =
        dates.length === 1
          ? { skill_id: skillId, reconciliation_date: dates[0], files }
          : { skill_id: skillId, reconciliation_dates: dates, files };
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!response.ok) throw new Error(await responseMessage(response, '后台任务启动失败。'));
      const result = (await response.json()) as { id?: unknown };
      if (typeof result.id !== 'string') throw new Error('后台任务返回结果无效。');
      window.location.assign(
        dates.length === 1
          ? `/dashboard/workflows/${encodeURIComponent(result.id)}`
          : `/dashboard/workflows/batches/${encodeURIComponent(result.id)}`
      );
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : '后台任务启动失败。');
    } finally {
      setWorking(false);
    }
  }

  const selectedDateLabel = selectedDates.length
    ? selectedDates
        .toSorted((left, right) => left.getTime() - right.getTime())
        .map((item) => format(item, 'yyyy-MM-dd'))
        .join('、')
    : '尚未选择';

  return (
    <div className='grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,28rem)]'>
      <Card>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Icons.sparkles className='size-5' /> 新建后台任务
          </CardTitle>
          <CardDescription>
            选择日期和材料后直接提交 Worker。任务会在后台运行，页面只展示状态和错误位置。
          </CardDescription>
        </CardHeader>
        <CardContent className='space-y-5'>
          <label className='grid gap-1.5 text-sm font-medium'>
            执行 Skill
            <select
              className='h-10 rounded-md border bg-background px-3 font-normal'
              value={skillId}
              onChange={(event) => setSkillId(event.target.value)}
              disabled={working || skills.length === 0}
            >
              {skills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name} · v{skill.version}
                </option>
              ))}
            </select>
          </label>

          <div className='rounded-lg border bg-muted/20 p-3'>
            <div className='flex items-start justify-between gap-3'>
              <div>
                <p className='text-sm font-medium'>选择核销日期</p>
                <p className='mt-1 text-xs text-muted-foreground'>
                  可以选择一天或多天，今天之后的日期不可选。
                </p>
              </div>
              <Badge variant='secondary'>{selectedDates.length} 天</Badge>
            </div>
            <Calendar
              mode='multiple'
              selected={selectedDates}
              onSelect={(dates) => setSelectedDates(dates ?? [])}
              disabled={{ after: today }}
              className='mx-auto mt-2'
              autoFocus
            />
            <p className='border-t pt-2 text-xs text-muted-foreground'>已选：{selectedDateLabel}</p>
          </div>

          {fileInputs.length > 0 && (
            <div className='space-y-3'>
              <div>
                <p className='text-sm font-medium'>任务材料</p>
                <p className='mt-1 text-xs text-muted-foreground'>
                  首次上传后平台会自动复用；需要更换时再上传。
                </p>
              </div>
              {fileInputs.map((input) => {
                const names = fileNames[input.role] ?? [];
                return (
                  <div key={input.role} className='rounded-lg border p-3'>
                    <div className='flex items-start justify-between gap-3'>
                      <div className='min-w-0'>
                        <p className='text-sm font-medium'>
                          {input.name}
                          {input.required && <span className='ml-1 text-destructive'>*</span>}
                        </p>
                        <p className='mt-1 text-xs text-muted-foreground'>{input.description}</p>
                        {names.length > 0 && (
                          <div className='mt-2 space-y-1 text-xs text-muted-foreground'>
                            {names.map((name, index) => (
                              <p key={`${name}-${index}`} className='truncate'>
                                {name}
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                      <label className='shrink-0 cursor-pointer rounded-md border px-3 py-2 text-xs font-medium transition-colors hover:bg-muted'>
                        {uploadingRole === input.role
                          ? '上传中…'
                          : names.length
                            ? '替换/新增'
                            : '选择文件'}
                        <input
                          type='file'
                          className='sr-only'
                          accept={input.extensions?.map((item) => `.${item}`).join(',')}
                          multiple={input.multiple}
                          disabled={Boolean(uploadingRole) || working}
                          onChange={(event) =>
                            void uploadMaterial(input.role, input.multiple, event)
                          }
                        />
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {error && (
            <Alert variant='destructive'>
              <AlertTitle>任务未启动</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button
            type='button'
            className='min-h-10 w-full sm:w-auto'
            onClick={() => void start()}
            disabled={working || Boolean(uploadingRole) || !skillId || selectedDates.length === 0}
          >
            {working
              ? '提交后台任务…'
              : selectedDates.length > 1
                ? `开始 ${selectedDates.length} 天任务`
                : '开始后台任务'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>最近任务</CardTitle>
          <CardDescription>任务提交后可离开页面，Worker 会继续执行。</CardDescription>
        </CardHeader>
        <CardContent className='space-y-2'>
          {workflows.length ? (
            workflows.map((workflow) => (
              <Link
                key={workflow.id}
                href={`/dashboard/workflows/${encodeURIComponent(workflow.id)}`}
                className='block rounded-lg border p-3 transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring'
              >
                <div className='flex items-start justify-between gap-2'>
                  <span className='font-medium'>{workflow.skill_name}</span>
                  <Badge variant={workflow.state === 'failed' ? 'destructive' : 'outline'}>
                    {stageLabel(workflow.stage)}
                  </Badge>
                </div>
                <p className='mt-1 text-xs text-muted-foreground'>
                  {workflow.reconciliation_date || '日期未设置'} · {workflow.progress}% ·{' '}
                  {workflow.progress_message}
                </p>
              </Link>
            ))
          ) : (
            <p className='rounded-lg border border-dashed p-4 text-sm text-muted-foreground'>
              暂无任务记录。
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
