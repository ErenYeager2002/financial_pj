'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { IconAlertTriangle, IconCheck, IconRobot, IconSettings } from '@tabler/icons-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Textarea } from '@/components/ui/textarea';
import type {
  AdminAssistantProfile,
  ModelConnection,
  PlatformFile,
  TaskDraft
} from '@/features/platform-api/types';
import { formatBytes } from '@/lib/utils';

interface AssistantWorkspaceProps {
  initialConfigured: boolean;
  files: PlatformFile[];
  isAdmin: boolean;
  profile?: AdminAssistantProfile;
  connections?: ModelConnection[];
}

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

function stateLabel(state: TaskDraft['state']): string {
  return {
    draft: '需要补充',
    ready: '可以确认',
    expired: '已过期',
    consumed: '已创建任务'
  }[state];
}

function valueText(value: unknown): string {
  if (typeof value === 'string') return value || '未填写';
  return JSON.stringify(value, null, 2);
}

export function AssistantWorkspace({
  initialConfigured,
  files,
  isAdmin,
  profile,
  connections = []
}: AssistantWorkspaceProps) {
  const router = useRouter();
  const [configured, setConfigured] = useState(initialConfigured);
  const [message, setMessage] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [draft, setDraft] = useState<TaskDraft | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [connectionId, setConnectionId] = useState(
    profile?.connection_id || connections[0]?.id || ''
  );
  const initialModel =
    profile?.model || connections.find((item) => item.id === connectionId)?.selected_model || '';
  const [model, setModel] = useState(initialModel);
  const [settingBusy, setSettingBusy] = useState(false);
  const [settingMessage, setSettingMessage] = useState('');
  const fileNames = useMemo(() => new Map(files.map((file) => [file.id, file.name])), [files]);
  const selectedConnection = connections.find((item) => item.id === connectionId);
  const candidates = draft?.candidates ?? [];
  const draftParameters = draft?.parameters ?? {};
  const draftFiles = draft?.files ?? {};
  const missingInputs = draft?.missing_inputs ?? [];
  const validationWarnings = draft?.validation_warnings ?? [];

  function toggleFile(fileId: string, checked: boolean) {
    setSelectedFiles((current) =>
      checked ? [...current, fileId] : current.filter((item) => item !== fileId)
    );
  }

  async function prepare() {
    setWorking(true);
    setError('');
    setDraft(null);
    const response = await fetch('/api/platform/assistant/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, file_ids: selectedFiles })
    });
    if (!response.ok) {
      setError(await responseMessage(response, '草稿生成失败。'));
      setWorking(false);
      return;
    }
    setDraft((await response.json()) as TaskDraft);
    setWorking(false);
  }

  function openTaskWizard() {
    if (!draft) return;
    router.push(
      `/dashboard/skills/${encodeURIComponent(draft.skill_id)}?draft=${encodeURIComponent(draft.id)}`
    );
  }

  async function discard() {
    if (!draft) return;
    setWorking(true);
    setError('');
    const response = await fetch(`/api/platform/task-drafts/${encodeURIComponent(draft.id)}`, {
      method: 'DELETE'
    });
    if (!response.ok) {
      setError(await responseMessage(response, '草稿删除失败。'));
      setWorking(false);
      return;
    }
    setDraft(null);
    setWorking(false);
  }

  async function saveProfile() {
    setSettingBusy(true);
    setSettingMessage('');
    const response = await fetch('/api/platform/admin/assistant-profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ connection_id: connectionId, model })
    });
    if (!response.ok) {
      setSettingMessage(await responseMessage(response, '配置保存失败。'));
      setSettingBusy(false);
      return;
    }
    setConfigured(true);
    setSettingMessage('默认模型已保存。');
    setSettingBusy(false);
  }

  return (
    <div className='grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]'>
      <div className='space-y-4'>
        {!configured && (
          <Alert variant='destructive'>
            <IconAlertTriangle />
            <AlertTitle>AI 助手尚未配置</AlertTitle>
            <AlertDescription>
              {isAdmin ? '请在右侧选择一个已连接的模型。' : '请联系管理员配置部门默认模型。'}
            </AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle className='flex items-center gap-2'>
              <IconRobot className='size-5' /> 描述你的财务任务
            </CardTitle>
            <CardDescription>
              助手只会生成任务草稿。请检查推荐的 Skill、参数和文件后再确认执行。
            </CardDescription>
          </CardHeader>
          <CardContent className='space-y-4'>
            <label htmlFor='assistant-message' className='grid gap-2 text-sm font-medium'>
              任务描述
              <Textarea
                id='assistant-message'
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                maxLength={4000}
                rows={5}
                placeholder='例如：使用本月银行流水和财务总账进行对账，金额容差 1 元。'
                disabled={!configured || working}
              />
            </label>
            <div className='space-y-2'>
              <p className='text-sm font-medium'>选择上传文件（可选）</p>
              {files.length ? (
                <div className='grid max-h-56 gap-2 overflow-y-auto rounded-lg border p-3 sm:grid-cols-2'>
                  {files.map((file) => (
                    <label
                      key={file.id}
                      htmlFor={`assistant-file-${file.id}`}
                      className='flex cursor-pointer items-start gap-3 rounded-md p-2 hover:bg-muted/60'
                    >
                      <Checkbox
                        id={`assistant-file-${file.id}`}
                        checked={selectedFiles.includes(file.id)}
                        onCheckedChange={(checked) => toggleFile(file.id, checked === true)}
                        disabled={!configured || working}
                      />
                      <span className='min-w-0 text-sm'>
                        <span className='block truncate font-medium'>{file.name}</span>
                        <span className='text-xs text-muted-foreground'>
                          {formatBytes(file.size_bytes)}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              ) : (
                <p className='rounded-lg border border-dashed p-4 text-sm text-muted-foreground'>
                  暂无上传文件。需要材料的任务请先到文件中心上传。
                </p>
              )}
            </div>
            {error && (
              <p role='alert' className='text-sm text-destructive'>
                {error}
              </p>
            )}
            <Button
              type='button'
              onClick={() => void prepare()}
              disabled={!configured || !message.trim() || working}
            >
              {working ? '处理中…' : '生成任务草稿'}
            </Button>
          </CardContent>
        </Card>

        {draft && (
          <Card>
            <CardHeader>
              <div className='flex flex-wrap items-start justify-between gap-3'>
                <div>
                  <CardTitle>{draft.skill_name}</CardTitle>
                  <CardDescription>
                    Skill {draft.skill_id} · 版本 {draft.skill_version}
                  </CardDescription>
                </div>
                <Badge variant={draft.state === 'ready' ? 'default' : 'secondary'}>
                  {stateLabel(draft.state)}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className='space-y-5'>
              <div>
                <div className='mb-1 flex justify-between text-sm'>
                  <span>推荐置信度</span>
                  <span>{Math.round(draft.confidence * 100)}%</span>
                </div>
                <div className='h-2 overflow-hidden rounded-full bg-muted'>
                  <div
                    className='h-full bg-primary'
                    style={{ width: `${draft.confidence * 100}%` }}
                  />
                </div>
              </div>
              {candidates.length > 1 && (
                <div>
                  <p className='mb-2 text-sm font-medium'>候选 Skill</p>
                  <div className='flex flex-wrap gap-2'>
                    {candidates.map((item) => (
                      <Badge key={item.id} variant='outline'>
                        {item.name}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              <div className='grid gap-4 md:grid-cols-2'>
                <div>
                  <p className='mb-2 text-sm font-medium'>参数</p>
                  <div className='space-y-2 rounded-lg border p-3 text-sm'>
                    {Object.entries(draftParameters).length ? (
                      Object.entries(draftParameters).map(([key, value]) => (
                        <div key={key} className='grid grid-cols-[minmax(6rem,0.4fr)_1fr] gap-2'>
                          <span className='text-muted-foreground'>{key}</span>
                          <pre className='whitespace-pre-wrap break-words font-sans'>
                            {valueText(value)}
                          </pre>
                        </div>
                      ))
                    ) : (
                      <span className='text-muted-foreground'>无额外参数</span>
                    )}
                  </div>
                </div>
                <div>
                  <p className='mb-2 text-sm font-medium'>文件分配</p>
                  <div className='space-y-2 rounded-lg border p-3 text-sm'>
                    {Object.entries(draftFiles).map(([role, value]) => {
                      const ids = Array.isArray(value) ? value : value ? [value] : [];
                      return (
                        <div key={role}>
                          <span className='text-muted-foreground'>{role}：</span>
                          {ids.map((id) => fileNames.get(id) ?? id).join('、') || '未选择'}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
              {(draft.clarification || missingInputs.length > 0) && (
                <Alert>
                  <IconAlertTriangle />
                  <AlertTitle>需要补充信息</AlertTitle>
                  <AlertDescription>
                    {draft.clarification || `缺少：${missingInputs.join('、')}`}
                  </AlertDescription>
                </Alert>
              )}
              {validationWarnings.map((warning) => (
                <Alert key={warning}>
                  <IconAlertTriangle />
                  <AlertDescription>{warning}</AlertDescription>
                </Alert>
              ))}
              {draft.confirmation_text && (
                <p className='rounded-lg bg-muted p-3 text-sm'>{draft.confirmation_text}</p>
              )}
              <div className='flex flex-wrap gap-2'>
                <Button
                  type='button'
                  onClick={openTaskWizard}
                  disabled={draft.state !== 'ready' || working}
                >
                  <IconCheck className='size-4' /> 进入任务向导
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  onClick={() => void discard()}
                  disabled={working}
                >
                  删除草稿
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {isAdmin && (
        <Card className='h-fit'>
          <CardHeader>
            <CardTitle className='flex items-center gap-2 text-base'>
              <IconSettings className='size-4' /> 助手默认模型
            </CardTitle>
            <CardDescription>设置仅供本部门 AI 助手使用的模型。</CardDescription>
          </CardHeader>
          <CardContent className='space-y-4'>
            {connections.length ? (
              <>
                <label className='grid gap-1.5 text-sm font-medium'>
                  模型连接
                  <select
                    className='h-9 rounded-md border bg-background px-3 font-normal'
                    value={connectionId}
                    onChange={(event) => {
                      const next = connections.find((item) => item.id === event.target.value);
                      setConnectionId(event.target.value);
                      setModel(next?.selected_model ?? next?.models[0] ?? '');
                    }}
                  >
                    {connections.map((connection) => (
                      <option
                        key={connection.id}
                        value={connection.id}
                        disabled={connection.status !== 'connected'}
                      >
                        {connection.provider_name} · {connection.api_key_hint}
                      </option>
                    ))}
                  </select>
                </label>
                <label className='grid gap-1.5 text-sm font-medium'>
                  默认模型
                  <select
                    className='h-9 rounded-md border bg-background px-3 font-normal'
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                  >
                    {(selectedConnection?.models ?? []).map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                {settingMessage && (
                  <p className='text-sm text-muted-foreground'>{settingMessage}</p>
                )}
                <Button
                  type='button'
                  className='w-full'
                  onClick={() => void saveProfile()}
                  disabled={!connectionId || !model || settingBusy}
                >
                  {settingBusy ? '保存中…' : '保存默认模型'}
                </Button>
              </>
            ) : (
              <p className='text-sm text-muted-foreground'>
                暂无已保存的模型连接，请先在原平台的模型设置中添加。
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
