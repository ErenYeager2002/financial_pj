'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  IconAlertTriangle,
  IconCheck,
  IconLoader2,
  IconRobot,
  IconSend,
  IconSettings
} from '@tabler/icons-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollableCollection } from '@/components/ui/scrollable-collection';
import { Checkbox } from '@/components/ui/checkbox';
import { Textarea } from '@/components/ui/textarea';
import { parseAgentWireEvent, type AgentWireEvent } from '@/features/agent-runtime/agent-wire';
import { draftCompletionMessage } from '@/features/ai-chat/assistant-message';
import type {
  AdminAssistantProfile,
  AssistantConversation,
  ModelConnection,
  PlatformFile,
  TaskDraft
} from '@/features/platform-api/types';
import { createClientId } from '@/lib/client-id';
import { formatBytes } from '@/lib/utils';

interface AssistantWorkspaceProps {
  initialConfigured: boolean;
  files: PlatformFile[];
  isAdmin: boolean;
  profile?: AdminAssistantProfile;
  connections?: ModelConnection[];
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

const WELCOME_MESSAGE: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content:
    '你好，我是财务平台 AI 助手。你可以直接问我业务问题、查看正在运行的任务，或描述想使用的 Skill。'
};

const CHAT_SESSION_STORAGE_KEY = 'financial-platform-assistant-session';

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

async function consumeAgentStream(
  response: Response,
  onEvent: (event: AgentWireEvent) => void
): Promise<void> {
  if (!response.body) throw new Error('AI 助手没有返回可读取的消息流。');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const consumeFrame = (frame: string) => {
    const data = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim())
      .join('\n');
    if (!data) return;
    try {
      onEvent(parseAgentWireEvent(JSON.parse(data)));
    } catch {
      throw new Error('AI 助手返回了无法识别的事件。');
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? '';
    for (const frame of frames) consumeFrame(frame);
    if (done) break;
  }
  if (buffer.trim()) consumeFrame(buffer);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function draftFromDetails(value: unknown): TaskDraft | null {
  if (!isRecord(value) || !isRecord(value.draft)) return null;
  const draft = value.draft;
  return typeof draft.id === 'string' && typeof draft.skill_name === 'string'
    ? (draft as unknown as TaskDraft)
    : null;
}

function assistantMessage(
  current: ChatMessage[],
  id: string,
  update: (content: string) => string
): ChatMessage[] {
  return current.map((item) =>
    item.id === id ? { ...item, content: update(item.content) } : item
  );
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
  const [input, setInput] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [draft, setDraft] = useState<TaskDraft | null>(null);
  const [sessionId, setSessionId] = useState('');
  const [historyLoading, setHistoryLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [toolMessage, setToolMessage] = useState('');
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

  useEffect(() => {
    let cancelled = false;

    async function loadConversation() {
      let conversation: AssistantConversation | null = null;
      const storedSessionId = window.localStorage.getItem(CHAT_SESSION_STORAGE_KEY) ?? '';
      if (storedSessionId) {
        const storedResponse = await fetch(
          `/api/platform/assistant/conversations/${encodeURIComponent(storedSessionId)}`,
          { cache: 'no-store' }
        ).catch(() => null);
        if (storedResponse?.ok) {
          conversation = (await storedResponse.json()) as AssistantConversation;
        }
      }
      if (!conversation) {
        const latestResponse = await fetch('/api/platform/assistant/conversations/latest', {
          cache: 'no-store'
        }).catch(() => null);
        if (latestResponse?.ok) {
          conversation = (await latestResponse.json()) as AssistantConversation | null;
        }
      }
      if (cancelled) return;
      if (conversation?.messages?.length) {
        setSessionId(conversation.session_id);
        window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, conversation.session_id);
        setMessages(
          conversation.messages
            .filter((item) => item.role === 'user' || item.role === 'assistant')
            .map((item) => ({
              id: item.id,
              role: item.role as 'user' | 'assistant',
              content: item.content
            }))
        );
      }
      setHistoryLoading(false);
    }

    void loadConversation();
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleFile(fileId: string, checked: boolean) {
    setSelectedFiles((current) =>
      checked ? [...current, fileId] : current.filter((item) => item !== fileId)
    );
  }

  async function sendMessage(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const message = input.trim();
    if (!message || !configured || historyLoading || working) return;

    const activeSessionId = sessionId || createClientId();
    if (!sessionId) {
      setSessionId(activeSessionId);
      window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, activeSessionId);
    }
    const assistantId = createClientId();
    setMessages((current) => [
      ...current,
      { id: createClientId(), role: 'user', content: message },
      { id: assistantId, role: 'assistant', content: '' }
    ]);
    setInput('');
    setDraft(null);
    setToolMessage('');
    setError('');
    setWorking(true);

    let response: Response;
    try {
      response = await fetch('/api/platform/assistant/turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: activeSessionId,
          message,
          file_ids: selectedFiles
        })
      });
    } catch {
      setError('AI 助手连接失败。');
      setWorking(false);
      return;
    }

    if (!response.ok) {
      setError(await responseMessage(response, 'AI 助手处理失败。'));
      setMessages((current) =>
        assistantMessage(current, assistantId, (content) => content || '这次请求没有完成。')
      );
      setWorking(false);
      return;
    }

    try {
      await consumeAgentStream(response, (event) => {
        if (event.type === 'text_delta') {
          setMessages((current) =>
            assistantMessage(current, assistantId, (content) => content + event.delta)
          );
        }
        if (event.type === 'tool_start') {
          setToolMessage(
            event.toolName === 'prepare_context'
              ? '正在准备会话上下文…'
              : `正在查询：${event.toolName}`
          );
        }
        if (event.type === 'tool_result') {
          const nextDraft = draftFromDetails(event.details);
          if (nextDraft) {
            setDraft(nextDraft);
            setMessages((current) =>
              assistantMessage(current, assistantId, (content) =>
                draftCompletionMessage(content, nextDraft.skill_name)
              )
            );
          }
          setToolMessage(
            event.isError
              ? '查询未完成。'
              : event.toolName === 'prepare_context'
                ? '正在生成回答…'
                : '平台数据已返回给 AI。'
          );
        }
        if (event.type === 'await_confirmation') setToolMessage(event.message);
        if (event.type === 'error') {
          setError(event.message);
          setMessages((current) =>
            assistantMessage(current, assistantId, (content) => content || event.message)
          );
        }
      });
    } catch (streamError) {
      const messageText = streamError instanceof Error ? streamError.message : 'AI 助手处理失败。';
      setError(messageText);
      setMessages((current) =>
        assistantMessage(current, assistantId, (content) => content || messageText)
      );
    }
    setWorking(false);
  }

  function openTaskWizard() {
    if (!draft) return;
    router.push(
      `/dashboard/skills/${encodeURIComponent(draft.skill_id)}/run?draft=${encodeURIComponent(draft.id)}`
    );
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
      <Card className='flex min-h-[38rem] flex-col'>
        <CardHeader className='border-b'>
          <CardTitle className='flex items-center gap-2'>
            <IconRobot className='size-5' /> AI 助手
          </CardTitle>
          <CardDescription>查询任务时，助手只读取当前账号有权查看的实时状态。</CardDescription>
        </CardHeader>
        <CardContent className='flex min-h-0 flex-1 flex-col gap-4 p-4'>
          {!configured && (
            <Alert variant='destructive'>
              <IconAlertTriangle />
              <AlertTitle>AI 助手尚未配置</AlertTitle>
              <AlertDescription>
                {isAdmin ? '请在右侧选择一个已连接的模型。' : '请联系管理员配置部门默认模型。'}
              </AlertDescription>
            </Alert>
          )}

          <ScrollableCollection
            ariaLabel='对话消息'
            className='min-h-0 flex-1 rounded-lg border bg-muted/20 p-4'
            contentClassName='space-y-4'
            followEnd
          >
            {messages.map((message) => (
              <div
                key={message.id}
                className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
              >
                <div
                  className={
                    message.role === 'user'
                      ? 'max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-3 text-sm text-primary-foreground'
                      : 'max-w-[85%] rounded-2xl rounded-bl-sm border bg-background px-4 py-3 text-sm'
                  }
                >
                  {message.content || (
                    <IconLoader2 className='size-4 animate-spin' aria-label='正在生成回复' />
                  )}
                </div>
              </div>
            ))}
          </ScrollableCollection>

          {toolMessage && <p className='text-xs text-muted-foreground'>{toolMessage}</p>}
          {error && (
            <p role='alert' className='text-sm text-destructive'>
              {error}
            </p>
          )}
          <form className='flex items-end gap-2' onSubmit={(event) => void sendMessage(event)}>
            <Textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              maxLength={4000}
              rows={3}
              placeholder='输入消息，例如：查看我正在运行的任务，或解释这个 Skill 是做什么的。'
              disabled={!configured || historyLoading || working}
              aria-label='发送给 AI 助手的消息'
            />
            <Button
              type='submit'
              size='icon'
              className='size-11 shrink-0'
              disabled={!configured || historyLoading || !input.trim() || working}
              aria-label='发送消息'
            >
              {working ? (
                <IconLoader2 className='size-4 animate-spin' />
              ) : (
                <IconSend className='size-4' />
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className='space-y-4'>
        <Card>
          <CardHeader>
            <CardTitle className='text-base'>相关文件</CardTitle>
            <CardDescription>文件内容仍受平台权限控制。</CardDescription>
          </CardHeader>
          <CardContent>
            {files.length ? (
              <ScrollableCollection ariaLabel='AI 助手相关文件' contentClassName='grid gap-2'>
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
                      <span className='block truncate font-medium'>{fileNames.get(file.id)}</span>
                      <span className='text-xs text-muted-foreground'>
                        {formatBytes(file.size_bytes)}
                      </span>
                    </span>
                  </label>
                ))}
              </ScrollableCollection>
            ) : (
              <p className='text-sm text-muted-foreground'>文件中心暂无上传文件。</p>
            )}
          </CardContent>
        </Card>

        {draft && (
          <Card>
            <CardHeader>
              <CardTitle className='text-base'>已生成任务草稿</CardTitle>
              <CardDescription>
                {draft.skill_name} · {draft.skill_version}
              </CardDescription>
            </CardHeader>
            <CardContent className='space-y-3'>
              <Badge variant={draft.state === 'ready' ? 'default' : 'secondary'}>
                {draft.state}
              </Badge>
              {draft.clarification && (
                <p className='text-sm text-muted-foreground'>{draft.clarification}</p>
              )}
              <Button type='button' onClick={openTaskWizard} disabled={draft.state !== 'ready'}>
                <IconCheck className='size-4' /> 打开任务
              </Button>
            </CardContent>
          </Card>
        )}

        {isAdmin && (
          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2 text-base'>
                <IconSettings className='size-4' /> 助手默认模型
              </CardTitle>
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
                <p className='text-sm text-muted-foreground'>暂无已保存的模型连接。</p>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
