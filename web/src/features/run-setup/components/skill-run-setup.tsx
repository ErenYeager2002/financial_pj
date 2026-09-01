'use client';

import Link from 'next/link';
import { useMemo, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import { FilePreview } from '@/components/ui/file-preview';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type {
  PlatformFile,
  RunDetail,
  SkillDetail,
  TaskDraft
} from '@/features/platform-api/types';
import type { SkillExecutionExperience } from '@/features/skills/execution-experience';
import {
  confirmRunMutation,
  confirmTaskDraftMutation,
  createRunMutation,
  deleteSkillFileMutation,
  uploadSkillFileMutation
} from '@/features/run-setup/api/mutations';
import { isRunnableSkill } from '@/features/run-setup/run-eligibility';
import { createClientId } from '@/lib/client-id';
import { cn } from '@/lib/utils';

interface SchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  pattern?: string;
  enum?: unknown[];
}

type FilesByRole = Record<string, PlatformFile[]>;
type Issues = Record<string, string>;

function schemaProperties(skill: SkillDetail): Array<[string, SchemaProperty]> {
  const properties = skill.input_schema?.properties;
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return [];
  return Object.entries(properties).filter(
    (entry): entry is [string, SchemaProperty] =>
      typeof entry[1] === 'object' && entry[1] !== null && !Array.isArray(entry[1])
  );
}

function initialParameters(properties: Array<[string, SchemaProperty]>): Record<string, unknown> {
  return Object.fromEntries(
    properties.map(([name, property]) => {
      if ('default' in property) return [name, property.default];
      if (property.type === 'boolean') return [name, false];
      return [name, ''];
    })
  );
}

function extension(name: string): string {
  const index = name.lastIndexOf('.');
  return index < 0 ? '' : name.slice(index + 1).toLowerCase();
}

function validateParameters(
  properties: Array<[string, SchemaProperty]>,
  required: Set<string>,
  values: Record<string, unknown>
): Issues {
  const issues: Issues = {};
  for (const [name, property] of properties) {
    const value = values[name];
    if (required.has(name) && (value === undefined || value === null || value === '')) {
      issues[name] = '此参数为必填项。';
      continue;
    }
    if (value === '' || value === undefined || value === null) continue;
    if (property.type === 'number' || property.type === 'integer') {
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        issues[name] = '请输入有效数字。';
        continue;
      }
      if (property.type === 'integer' && !Number.isInteger(value)) {
        issues[name] = '请输入整数。';
      } else if (property.minimum !== undefined && value < property.minimum) {
        issues[name] = `不能小于 ${property.minimum}。`;
      } else if (property.maximum !== undefined && value > property.maximum) {
        issues[name] = `不能大于 ${property.maximum}。`;
      }
    }
    if (property.type === 'string' && property.pattern && typeof value === 'string') {
      try {
        if (!new RegExp(property.pattern).test(value)) issues[name] = '填写格式不符合要求。';
      } catch {
        issues[name] = '参数规则配置无效，请联系管理员。';
      }
    }
  }
  return issues;
}

function stateLabel(state: string): string {
  const labels: Record<string, string> = {
    waiting_confirmation: '等待确认',
    queued: '已进入队列',
    running: '处理中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消'
  };
  return labels[state] ?? state;
}

interface SkillRunSetupProps {
  skill: SkillDetail;
  experience: SkillExecutionExperience;
  draft?: TaskDraft;
  draftFiles?: PlatformFile[];
}

function filesFromDraft(
  skill: SkillDetail,
  draft: TaskDraft | undefined,
  files: PlatformFile[]
): FilesByRole {
  if (!draft) return {};
  const byId = new Map(files.map((file) => [file.id, file]));
  return Object.fromEntries(
    (skill.file_inputs ?? []).map((input) => {
      const value = draft.files?.[input.role];
      const ids = Array.isArray(value) ? value : value ? [value] : [];
      return [input.role, ids.map((id) => byId.get(id)).filter((item) => item !== undefined)];
    })
  );
}

export function SkillRunSetup({ skill, experience, draft, draftFiles = [] }: SkillRunSetupProps) {
  const properties = useMemo(() => schemaProperties(skill), [skill]);
  const requiredParameters = useMemo(
    () =>
      new Set(
        Array.isArray(skill.input_schema?.required)
          ? skill.input_schema.required.filter((item): item is string => typeof item === 'string')
          : []
      ),
    [skill]
  );
  const [parameters, setParameters] = useState<Record<string, unknown>>(() => ({
    ...initialParameters(properties),
    ...draft?.parameters
  }));
  const [filesByRole, setFilesByRole] = useState<FilesByRole>(() =>
    filesFromDraft(skill, draft, draftFiles)
  );
  const [fileIssues, setFileIssues] = useState<Issues>({});
  const [parameterIssues, setParameterIssues] = useState<Issues>({});
  const [uploadingRole, setUploadingRole] = useState<string | null>(null);
  const [removingFileId, setRemovingFileId] = useState<string | null>(null);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [createdRun, setCreatedRun] = useState<RunDetail | null>(null);
  const idempotencyKey = useRef<string>(createClientId());

  const uploadMutation = useMutation(uploadSkillFileMutation);
  const deleteMutation = useMutation(deleteSkillFileMutation);
  const createMutation = useMutation(createRunMutation);
  const confirmMutation = useMutation(confirmRunMutation);
  const draftMutation = useMutation(confirmTaskDraftMutation);
  const originalDraftFileIds = useMemo(
    () => new Set(draftFiles.map((file) => file.id)),
    [draftFiles]
  );
  const busy =
    uploadMutation.isPending ||
    deleteMutation.isPending ||
    createMutation.isPending ||
    draftMutation.isPending;

  function collectFileIssues(nextFiles = filesByRole): Issues {
    const issues: Issues = {};
    for (const input of skill.file_inputs ?? []) {
      const count = nextFiles[input.role]?.length ?? 0;
      if (input.required && count < input.min_files) {
        issues[input.role] = `至少需要上传 ${input.min_files} 个文件。`;
      } else if (!input.multiple && count > 1) {
        issues[input.role] = '此用途只允许一个文件。';
      }
    }
    return issues;
  }

  function localFileIssue(
    file: File,
    input: NonNullable<SkillDetail['file_inputs']>[number]
  ): string | null {
    const allowed = input.extensions ?? [];
    if (allowed.length && !allowed.some((item) => item.toLowerCase() === extension(file.name))) {
      return `${file.name} 格式不支持，请上传 ${allowed.join('、')} 文件。`;
    }
    const maxBytes = (input.max_size_mb ?? 100) * 1024 * 1024;
    if (file.size <= 0) return `${file.name} 是空文件。`;
    if (file.size > maxBytes) return `${file.name} 不能超过 ${input.max_size_mb ?? 100} MB。`;
    return null;
  }

  async function handleUpload(
    input: NonNullable<SkillDetail['file_inputs']>[number],
    selected: FileList | null
  ) {
    if (!selected?.length || createdRun) return;
    const chosen = input.multiple ? Array.from(selected) : [selected[0]];
    if ((filesByRole[input.role]?.length ?? 0) + chosen.length > 20) {
      toast.error('每个文件用途最多保留 20 个文件。');
      return;
    }
    const issue = chosen.map((file) => localFileIssue(file, input)).find(Boolean);
    if (issue) {
      setFileIssues((current) => ({ ...current, [input.role]: issue }));
      toast.error(issue);
      return;
    }

    setUploadingRole(input.role);
    const uploaded: PlatformFile[] = [];
    try {
      for (const file of chosen) {
        uploaded.push(
          await uploadMutation.mutateAsync({ skillId: skill.id, role: input.role, file })
        );
      }
      const previous = filesByRole[input.role] ?? [];
      const nextRoleFiles = input.multiple ? [...previous, ...uploaded] : uploaded;
      const nextFiles = { ...filesByRole, [input.role]: nextRoleFiles };
      setFilesByRole(nextFiles);
      setFileIssues(collectFileIssues(nextFiles));
      if (!input.multiple && previous.length) {
        await Promise.allSettled(previous.map((file) => deleteMutation.mutateAsync(file.id)));
      }
      toast.success(uploaded.length > 1 ? `已上传 ${uploaded.length} 个文件。` : '文件已上传。');
    } catch (error) {
      if (uploaded.length) {
        setFilesByRole((current) => ({
          ...current,
          [input.role]: [...(current[input.role] ?? []), ...uploaded]
        }));
      }
      const text = error instanceof Error ? error.message : '文件上传失败。';
      setFileIssues((current) => ({ ...current, [input.role]: text }));
      toast.error(text);
    } finally {
      setUploadingRole(null);
    }
  }

  async function handleRemove(role: string, fileId: string) {
    if (createdRun) return;
    setRemovingFileId(fileId);
    try {
      if (!originalDraftFileIds.has(fileId)) await deleteMutation.mutateAsync(fileId);
      const nextFiles = {
        ...filesByRole,
        [role]: (filesByRole[role] ?? []).filter((file) => file.id !== fileId)
      };
      setFilesByRole(nextFiles);
      setFileIssues(collectFileIssues(nextFiles));
      toast.success('文件已移除。');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '文件删除失败。');
    } finally {
      setRemovingFileId(null);
    }
  }

  function openConfirmation() {
    const nextFileIssues = collectFileIssues();
    const nextParameterIssues = validateParameters(properties, requiredParameters, parameters);
    setFileIssues(nextFileIssues);
    setParameterIssues(nextParameterIssues);
    if (Object.keys(nextFileIssues).length || Object.keys(nextParameterIssues).length) {
      toast.error('请先补齐或修正文件和参数。');
      return;
    }
    if (skill.risk.requires_confirmation) {
      setConfirmationOpen(true);
      return;
    }
    void createAndConfirm();
  }

  function moveRoleFile(role: string, fileId: string, direction: -1 | 1) {
    setFilesByRole((current) => {
      const files = [...(current[role] ?? [])];
      const index = files.findIndex((file) => file.id === fileId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= files.length) return current;
      [files[index], files[target]] = [files[target], files[index]];
      return { ...current, [role]: files };
    });
  }

  function runFiles(): Record<string, string | string[]> {
    return Object.fromEntries(
      (skill.file_inputs ?? [])
        .map((input) => {
          const ids = (filesByRole[input.role] ?? []).map((file) => file.id);
          return [input.role, input.multiple ? ids : ids[0]];
        })
        .filter((entry) => entry[1] !== undefined && (!Array.isArray(entry[1]) || entry[1].length))
    );
  }

  async function createAndConfirm() {
    let run: RunDetail | null = null;
    try {
      run = draft
        ? await draftMutation.mutateAsync({
            draftId: draft.id,
            parameters,
            files: runFiles()
          })
        : await createMutation.mutateAsync({
            skill_id: skill.id,
            message: '',
            parameters,
            files: runFiles(),
            idempotency_key: idempotencyKey.current
          });
      setCreatedRun(run);
      if (run.confirmation_required && run.state === 'waiting_confirmation') {
        try {
          const confirmation = await confirmMutation.mutateAsync(run.id);
          run = { ...run, state: confirmation.state, progress_message: confirmation.message };
          setCreatedRun(run);
        } catch (error) {
          const text = error instanceof Error ? error.message : '任务确认失败。';
          toast.error(`任务已创建，但尚未进入队列：${text}`);
          setConfirmationOpen(false);
          return;
        }
      }
      toast.success('任务已创建并进入队列。');
      setConfirmationOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '任务创建失败。');
    }
  }

  async function retryConfirmation() {
    if (!createdRun) return;
    try {
      const confirmation = await confirmMutation.mutateAsync(createdRun.id);
      setCreatedRun({
        ...createdRun,
        state: confirmation.state,
        progress_message: confirmation.message
      });
      toast.success('任务已进入队列。');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '任务确认失败。');
    }
  }

  if (!isRunnableSkill(skill)) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>创建任务</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert>
            <Icons.info />
            <AlertTitle>当前不能创建标准任务</AlertTitle>
            <AlertDescription>只有已发布的标准只读 Skill 可以从此页面创建任务。</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  if (createdRun) {
    return (
      <Card>
        <CardHeader>
          <div className='flex items-center justify-between gap-3'>
            <CardTitle>任务已创建</CardTitle>
            <Badge variant={createdRun.state === 'waiting_confirmation' ? 'outline' : 'default'}>
              {stateLabel(createdRun.state)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className='space-y-4'>
          <Alert>
            <Icons.circleCheck />
            <AlertTitle>{createdRun.skill_name}</AlertTitle>
            <AlertDescription>{createdRun.progress_message}</AlertDescription>
          </Alert>
          <div className='grid gap-2 rounded-lg border p-3 text-sm sm:grid-cols-2'>
            <p>
              <span className='text-muted-foreground'>任务编号：</span>
              <span className='break-all font-mono'>{createdRun.id}</span>
            </p>
            <p>
              <span className='text-muted-foreground'>创建人：</span>
              {createdRun.owner_name}
            </p>
          </div>
          <div className='flex flex-wrap gap-2'>
            {createdRun.state === 'waiting_confirmation' && (
              <Button disabled={confirmMutation.isPending} onClick={retryConfirmation}>
                {confirmMutation.isPending && <Icons.spinner className='animate-spin' />}
                确认并进入队列
              </Button>
            )}
            <Link
              href={`/dashboard/skills/${encodeURIComponent(skill.id)}/tasks/${encodeURIComponent(createdRun.id)}`}
              className={cn(buttonVariants({ variant: 'outline' }))}
            >
              查看实时进度
            </Link>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {draft ? `核对草稿并${experience.creationTitle}` : experience.creationTitle}
        </CardTitle>
      </CardHeader>
      <CardContent className='space-y-6'>
        <section
          className={cn(
            'grid gap-4 rounded-xl border bg-muted/25 p-4',
            experience.family === 'comparison' && 'md:grid-cols-[1.1fr_0.9fr]',
            experience.family === 'workbook' && 'border-l-4 border-l-primary',
            experience.family === 'batch' && 'bg-muted/40',
            experience.family === 'advisory' && 'border-dashed'
          )}
          aria-labelledby='experience-purpose'
        >
          <div className='space-y-2'>
            <h3 id='experience-purpose' className='font-medium'>
              {experience.inputHeading}
            </h3>
            <p className='text-sm leading-6 text-muted-foreground'>{experience.purpose}</p>
            <p className='text-sm leading-6'>{experience.inputHint}</p>
          </div>
          <div className='space-y-2'>
            <p className='text-sm font-medium'>{experience.reviewTitle}</p>
            <PaginatedCollection
              ariaLabel='任务提交前检查项'
              contentClassName='space-y-2 text-sm text-muted-foreground'
            >
              {experience.reviewItems.map((item) => (
                <div key={item} className='flex gap-2'>
                  <Icons.circleCheck className='mt-0.5 size-4 shrink-0 text-primary' />
                  <span>{item}</span>
                </div>
              ))}
            </PaginatedCollection>
          </div>
        </section>

        <div className='space-y-4'>
          {(skill.file_inputs ?? []).map((input) => {
            const uploaded = filesByRole[input.role] ?? [];
            return (
              <div key={input.role} className='space-y-2 rounded-lg border p-4'>
                <div className='flex flex-wrap items-start justify-between gap-2'>
                  <div>
                    <Label htmlFor={`file-${input.role}`}>{input.name}</Label>
                    {input.description && (
                      <p className='mt-1 text-sm text-muted-foreground'>{input.description}</p>
                    )}
                  </div>
                  <Badge variant={input.required ? 'default' : 'outline'}>
                    {input.required ? '必需' : '可选'}
                  </Badge>
                </div>
                <Input
                  id={`file-${input.role}`}
                  type='file'
                  accept={(input.extensions ?? []).map((item) => `.${item}`).join(',')}
                  multiple={input.multiple}
                  disabled={busy || uploadingRole !== null}
                  onChange={(event) => {
                    void handleUpload(input, event.currentTarget.files);
                    event.currentTarget.value = '';
                  }}
                />
                <p className='text-xs text-muted-foreground'>
                  支持 {(input.extensions ?? []).join('、') || '任意格式'}；单个文件不超过{' '}
                  {input.max_size_mb ?? 100} MB
                  {input.multiple ? `；至少上传 ${input.min_files} 个` : ''}
                </p>
                {uploadingRole === input.role && (
                  <p className='flex items-center gap-2 text-sm text-muted-foreground'>
                    <Icons.spinner className='animate-spin' />
                    正在上传，请勿关闭页面…
                  </p>
                )}
                {experience.orderedFileRole === input.role && uploaded.length > 0 && (
                  <PaginatedCollection
                    ariaLabel='文件版本顺序'
                    className='rounded-lg bg-muted/40 p-3'
                    contentClassName='space-y-2'
                  >
                    {uploaded.map((file, index) => (
                      <div key={file.id} className='flex items-center gap-2 text-sm'>
                        <span className='w-16 shrink-0 font-medium'>
                          {index === uploaded.length - 1 ? '最新版' : `版本 ${index + 1}`}
                        </span>
                        <span className='min-w-0 flex-1 truncate'>{file.name}</span>
                        <Button
                          type='button'
                          size='icon'
                          variant='ghost'
                          disabled={index === 0}
                          aria-label={`上移 ${file.name}`}
                          onClick={() => moveRoleFile(input.role, file.id, -1)}
                        >
                          <Icons.chevronUp />
                        </Button>
                        <Button
                          type='button'
                          size='icon'
                          variant='ghost'
                          disabled={index === uploaded.length - 1}
                          aria-label={`下移 ${file.name}`}
                          onClick={() => moveRoleFile(input.role, file.id, 1)}
                        >
                          <Icons.chevronDown />
                        </Button>
                      </div>
                    ))}
                  </PaginatedCollection>
                )}
                <FilePreview
                  files={uploaded.map((file) => ({
                    id: file.id,
                    name: file.name,
                    type: file.content_type,
                    isUploading: removingFileId === file.id
                  }))}
                  onRemove={(fileId) => void handleRemove(input.role, fileId)}
                />
                {fileIssues[input.role] && (
                  <p className='text-sm text-destructive'>{fileIssues[input.role]}</p>
                )}
              </div>
            );
          })}
        </div>

        {properties.length > 0 && (
          <div className='space-y-4 border-t pt-5'>
            <h3 className='font-medium'>任务参数</h3>
            <div className='grid gap-4 md:grid-cols-2'>
              {properties.map(([name, property]) => (
                <div key={name} className='space-y-2'>
                  <Label htmlFor={`parameter-${name}`}>
                    {property.title ?? name}
                    {requiredParameters.has(name) ? ' *' : ''}
                  </Label>
                  {property.type === 'boolean' ? (
                    <label className='flex h-9 items-center gap-2 rounded-lg border px-3 text-sm'>
                      <Checkbox
                        checked={parameters[name] === true}
                        onCheckedChange={(checked) =>
                          setParameters((current) => ({ ...current, [name]: checked === true }))
                        }
                      />
                      {parameters[name] === true ? '是' : '否'}
                    </label>
                  ) : property.enum?.length ? (
                    <select
                      id={`parameter-${name}`}
                      className='border-input bg-background ring-offset-background focus-visible:ring-ring h-9 w-full rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none'
                      value={String(parameters[name] ?? '')}
                      onChange={(event) =>
                        setParameters((current) => ({
                          ...current,
                          [name]: event.currentTarget.value
                        }))
                      }
                    >
                      {!requiredParameters.has(name) && <option value=''>不指定</option>}
                      {property.enum.map((option) => (
                        <option key={String(option)} value={String(option)}>
                          {String(option)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Input
                      id={`parameter-${name}`}
                      type={
                        name === 'today'
                          ? 'date'
                          : property.type === 'number' || property.type === 'integer'
                            ? 'number'
                            : 'text'
                      }
                      step={
                        property.type === 'integer'
                          ? 1
                          : property.type === 'number'
                            ? 'any'
                            : undefined
                      }
                      min={property.minimum}
                      max={property.maximum}
                      value={String(parameters[name] ?? '')}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setParameters((current) => ({
                          ...current,
                          [name]:
                            property.type === 'number' || property.type === 'integer'
                              ? value === ''
                                ? ''
                                : Number(value)
                              : value
                        }));
                      }}
                    />
                  )}
                  {property.description && (
                    <p className='text-xs text-muted-foreground'>{property.description}</p>
                  )}
                  {parameterIssues[name] && (
                    <p className='text-sm text-destructive'>{parameterIssues[name]}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <section className='grid gap-4 border-t pt-5 md:grid-cols-2' aria-label='任务检查说明'>
          <div>
            <h3 className='font-medium'>提交前可确认</h3>
            <p className='mt-1 text-sm text-muted-foreground'>
              文件数量、格式、参数和上方列出的业务口径。
            </p>
          </div>
          <div>
            <h3 className='font-medium'>任务执行时检查</h3>
          <PaginatedCollection
            ariaLabel='任务执行时检查项'
            className='mt-1'
            contentClassName='space-y-1 text-sm text-muted-foreground'
          >
            {experience.workerChecks.map((item) => (
              <div key={item}>{item}</div>
            ))}
          </PaginatedCollection>
          </div>
        </section>

        <div className='flex flex-wrap items-center justify-between gap-3 border-t pt-5'>
          <p className='text-sm text-muted-foreground'>
            {skill.risk.requires_confirmation
              ? '核对业务口径后创建任务。'
              : '输入检查通过后直接创建任务。'}
          </p>
          <Button disabled={busy || uploadingRole !== null} onClick={openConfirmation}>
            {skill.action_label}
          </Button>
        </div>
      </CardContent>

      <AlertDialog open={confirmationOpen} onOpenChange={setConfirmationOpen}>
        <AlertDialogContent className='sm:max-w-lg'>
          <AlertDialogHeader>
            <AlertDialogTitle>确认任务输入</AlertDialogTitle>
            <AlertDialogDescription>
              请核对以下文件和参数。确认后任务将进入后台队列。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className='max-h-80 space-y-4 overflow-y-auto rounded-lg border p-3 text-sm'>
            <div>
              <p className='mb-2 font-medium'>文件</p>
              <PaginatedCollection
                ariaLabel='确认提交文件'
                contentClassName='space-y-1 text-muted-foreground'
              >
                {(skill.file_inputs ?? []).flatMap((input) =>
                  (filesByRole[input.role] ?? []).map((file) => (
                    <div key={file.id} className='flex justify-between gap-3'>
                      <span>{input.name}</span>
                      <span className='truncate'>{file.name}</span>
                    </div>
                  ))
                )}
              </PaginatedCollection>
            </div>
            {properties.length > 0 && (
              <div className='border-t pt-3'>
                <p className='mb-2 font-medium'>参数</p>
                <PaginatedCollection
                  ariaLabel='确认提交参数'
                  contentClassName='space-y-1 text-muted-foreground'
                >
                  {properties.map(([name, property]) => (
                    <div key={name} className='flex justify-between gap-3'>
                      <dt>{property.title ?? name}</dt>
                      <dd>
                        {typeof parameters[name] === 'boolean'
                          ? parameters[name]
                            ? '是'
                            : '否'
                          : String(parameters[name] ?? '') || '未填写'}
                      </dd>
                    </div>
                  ))}
                </PaginatedCollection>
              </div>
            )}
            <div className='border-t pt-3'>
              <p className='mb-2 font-medium'>{experience.reviewTitle}</p>
              <PaginatedCollection
                ariaLabel='确认提交检查项'
                contentClassName='space-y-1 text-muted-foreground'
              >
                {experience.reviewItems.map((item) => (
                  <div key={item}>{item}</div>
                ))}
              </PaginatedCollection>
            </div>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy || confirmMutation.isPending}>
              返回修改
            </AlertDialogCancel>
            <Button
              disabled={busy || confirmMutation.isPending}
              onClick={() => void createAndConfirm()}
            >
              {(busy || confirmMutation.isPending) && <Icons.spinner className='animate-spin' />}
              确认{skill.action_label}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
