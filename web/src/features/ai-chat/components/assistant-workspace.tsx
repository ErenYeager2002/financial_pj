'use client';

import type { FileInputSpec } from '@/features/platform-api/generated';

import { Suspense } from 'react';
import { RunDetailView } from '@/features/runs/components/run-detail';
import { skillSessionPrefix, belongsToSkillSession } from '../skill-chat-scope';
import { watchAssistantTurn } from '@/features/ai-chat/turn-recovery';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Icons } from '@/components/icons';
import { parseAgentWireEvent, type AgentWireEvent } from '@/features/agent-runtime/agent-wire';
import { draftCompletionMessage } from '@/features/ai-chat/assistant-message';
import { AssistantComposer } from '@/features/ai-chat/components/assistant-composer';
import { AssistantContextPanel } from '@/features/ai-chat/components/assistant-context-panel';
import { AssistantHeader } from '@/features/ai-chat/components/assistant-header';
import { AssistantModelSelector } from '@/features/ai-chat/components/assistant-model-selector';
import { AssistantShell } from '@/features/ai-chat/components/assistant-shell';
import {
  AssistantTranscript,
  type ChatMessage
} from '@/features/ai-chat/components/assistant-transcript';
import { MAX_SELECTED_FILES } from '@/features/ai-chat/components/selectable-input-file-picker-state';
import { Button } from '@/components/ui/button';
import type {
  AdminAssistantProfile,
  AssistantConversation,
  AssistantConversationSummary,
  ModelConnection,
  TaskDraft
} from '@/features/platform-api/types';
import { createClientId } from '@/lib/client-id';

interface AssistantWorkspaceProps {
  initialConfigured: boolean;
  initialModel: string;
  isAdmin: boolean;
  profile?: AdminAssistantProfile;
  connections?: ModelConnection[];
  skillId?: string;
  skillName?: string;
  fileInputs?: FileInputSpec[];
}

const WELCOME_MESSAGE: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content:
    '你好，我是财务平台 AI 助手。你可以直接问我业务问题、查看正在运行的任务，或描述想使用的 Skill。'
};

const CHAT_UI_STATE_PREFIX = 'financial-platform-assistant-state';

type PersistedAssistantState = {
  input?: string;
  selectedFiles?: string[];
  selectedFileNames?: Record<string, string>;
  pendingMessage?: string;
  draft?: unknown;
  runId?: string;
  invalidatedDraftId?: string;
};

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

async function parseJsonResponse<T>(response: Response | null): Promise<T | null> {
  if (!response?.ok) return null;
  try {
    return (await response.json()) as T;
  } catch {
    return null;
  }
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

function readPersistedAssistantState(sessionId: string): PersistedAssistantState | null {
  try {
    const raw = window.localStorage.getItem(`${CHAT_UI_STATE_PREFIX}:${sessionId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) return null;
    return parsed as PersistedAssistantState;
  } catch {
    return null;
  }
}

function conversationMessages(conversation: AssistantConversation): ChatMessage[] {
  return (conversation.messages ?? [])
    .filter((item) => item.role === 'user' || item.role === 'assistant')
    .map((item) => ({
      id: item.id,
      role: item.role as 'user' | 'assistant',
      content: item.content,
      createdAt: item.created_at
    }));
}

function clarificationFromDetails(value: unknown): string {
  if (!isRecord(value) || typeof value.clarification !== 'string') return '';
  return value.clarification.trim();
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
  initialModel,
  isAdmin,
  profile,
  connections = [],
  skillId,
  skillName,
  fileInputs = []
}: AssistantWorkspaceProps) {
  const router = useRouter();
  const [configured, setConfigured] = useState(initialConfigured);
  const [input, setInput] = useState('');
  const CHAT_SESSION_STORAGE_KEY = skillId ? `financial-platform-assistant-session:${skillId}` : 'financial-platform-assistant-session';
  const welcomeMessage: ChatMessage = skillId
    ? { id: 'welcome', role: 'assistant', content: skillId.startsWith('native--') ? `请上传材料并说明任务，我会按${skillName || '当前 Skill'}的步骤执行，并在本页提供结果。` : `请上传材料并告诉我需要怎样处理${skillName || '当前工具'}。我会依据此 Skill 的说明确认材料和参数，再生成可执行方案。` }
    : WELCOME_MESSAGE;
  const [runId, setRunId] = useState('');
  const [nativeRuns, setNativeRuns] = useState<Array<{id: string; state: string; result?: Record<string, unknown>}>>([]);
  const nativeSelectionRef = useRef('');
  const invalidDraftRef = useRef<string | null>(null);
  const [startingRun, setStartingRun] = useState(false);
  const [uploadWorking, setUploadWorking] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFileNames, setSelectedFileNames] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [draft, setDraft] = useState<TaskDraft | null>(null);
  const [sessionId, setSessionId] = useState('');
  const [conversations, setConversations] = useState<AssistantConversationSummary[]>([]);
  const [historyListLoading, setHistoryListLoading] = useState(true);
  const [historyListError, setHistoryListError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyCheckedAt, setHistoryCheckedAt] = useState('');
  const [historical, setHistorical] = useState(false);
  const [streamWorking, setWorking] = useState(false);
  const [backgroundWorking, setBackgroundWorking] = useState(false);
  const working = streamWorking || backgroundWorking || startingRun || uploadWorking;
  const [, setToolMessage] = useState('');
  const [pendingMessage, setPendingMessage] = useState('');
  const [error, setError] = useState('');
  const turnControllerRef = useRef<AbortController | null>(null);
  const turnReadyRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadConversation() {
      try {
        let conversation: AssistantConversation | null = null;
        const storedSessionId = window.localStorage.getItem(CHAT_SESSION_STORAGE_KEY) ?? '';
        const [storedResponse, latestResponse, listResponse] = await Promise.all([
          storedSessionId
            ? fetch(
                `/api/platform/assistant/conversations/${encodeURIComponent(storedSessionId)}`,
                { cache: 'no-store' }
              ).catch(() => null)
            : Promise.resolve(null),
          skillId ? Promise.resolve(null) : fetch('/api/platform/assistant/conversations/latest', { cache: 'no-store' }).catch(() => null),
          fetch('/api/platform/assistant/conversations', { cache: 'no-store' }).catch(() => null)
        ]);
        if (cancelled) return;

        const listPayload = await parseJsonResponse<unknown>(listResponse);
        if (Array.isArray(listPayload)) {
          setConversations((listPayload as AssistantConversationSummary[]).filter(item => belongsToSkillSession(item.session_id, skillId)));
          setHistoryListError('');
        } else {
          setHistoryListError('历史会话加载失败。');
        }
        const storedPayload = await parseJsonResponse<unknown>(storedResponse);
        if (isRecord(storedPayload) && Array.isArray(storedPayload.messages)) {
          conversation = storedPayload as unknown as AssistantConversation;
        }
        if (!conversation) {
          const latestPayload = await parseJsonResponse<unknown>(latestResponse);
          if (isRecord(latestPayload) && Array.isArray(latestPayload.messages)) {
            conversation = latestPayload as unknown as AssistantConversation;
          }
        }
        if (conversation?.messages?.length && belongsToSkillSession(conversation.session_id, skillId)) {
          setSessionId(conversation.session_id);
          window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, conversation.session_id);
          setMessages(conversationMessages(conversation));
          const storedState = readPersistedAssistantState(conversation.session_id);
          if (storedState) {
            invalidDraftRef.current = storedState.invalidatedDraftId || null;
            setInput(typeof storedState.input === 'string' ? storedState.input : '');
            setSelectedFiles(
              Array.isArray(storedState.selectedFiles)
                ? storedState.selectedFiles.filter((item): item is string => typeof item === 'string')
                : []
            );
            setSelectedFileNames(
              isRecord(storedState.selectedFileNames)
                ? Object.fromEntries(
                    Object.entries(storedState.selectedFileNames).filter(
                      ([key, value]) => typeof key === 'string' && typeof value === 'string'
                    )
                  )
                : {}
            );
            setPendingMessage(
              typeof storedState.pendingMessage === 'string' ? storedState.pendingMessage : ''
            );
            setDraft(draftFromDetails({ draft: storedState.draft }));
            setRunId(storedState.runId || "");
          }
          setHistorical(true);
          setHistoryCheckedAt(new Date().toISOString());
        } else {
          setMessages([welcomeMessage]);
          setHistorical(false);
        }
      } catch {
        if (!cancelled) {
          setHistoryListError('历史会话加载失败。');
          setMessages([welcomeMessage]);
          setHistorical(false);
        }
      } finally {
        if (!cancelled) {
          setHistoryLoading(false);
          setHistoryListLoading(false);
        }
      }
    }

    void loadConversation();
    return () => {
      cancelled = true;
      turnControllerRef.current?.abort();
    };
  }, [skillId]);

  useEffect(() => {
    if (!sessionId || historyLoading || streamWorking) return;
    setBackgroundWorking(true);
    const recovery = new AbortController();
    const stopWatching = watchAssistantTurn(sessionId, {
      update: (value, active) => {
        if (!isRecord(value) || !Array.isArray(value.messages)) return;
        const conversation = value as unknown as AssistantConversation;
        const recovered = conversationMessages(conversation);
        setMessages(active ? [...recovered, {
          id: `background-${sessionId}`, role: 'assistant', content: '正在后台生成回复，完成后会自动显示。'
        }] : recovered);
        if (skillId && !active) {
          const last = conversation.messages?.at(-1);
          const savedId = last?.role === 'assistant' ? last.data?.draft_id : undefined;
          if (typeof savedId === 'string' && invalidDraftRef.current !== savedId) {
            void fetch(`/api/platform/task-drafts/${encodeURIComponent(savedId)}`, { cache: 'no-store', signal: recovery.signal })
              .then(async response => {
                if (!response.ok) return;
                const saved = await response.json() as TaskDraft & { run_id?: string };
                if (recovery.signal.aborted || saved.skill_id !== skillId || invalidDraftRef.current === savedId) return;
                setDraft(saved);
                if (saved.run_id) setRunId(saved.run_id);
              }).catch(() => undefined);
          }
        }
        setBackgroundWorking(active);
        setHistorical(!active);
        setHistoryCheckedAt(new Date().toISOString());
        setError(!active && recovered.at(-1)?.role === 'user'
          ? '未找到这条消息的已保存回复。请先核实任务状态，避免重复发送执行指令。'
          : '');
      },
      error: setError
    });
    return () => { recovery.abort(); stopWatching(); };
  }, [sessionId, historyLoading, streamWorking, skillId]);

  useEffect(() => {
    if (!skillId?.startsWith('native--') || !sessionId || historyLoading) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      try {
        const response = await fetch(`/api/platform/assistant/native-skills/${encodeURIComponent(skillId.slice('native--'.length))}/runs?session_id=${encodeURIComponent(sessionId)}`, {cache: 'no-store', signal: controller.signal});
        if (response.ok) {
          const runs = await response.json() as Array<{id: string; state: string; result?: Record<string, unknown>}>;
          if (!controller.signal.aborted) {
            setNativeRuns(runs);
            const selected = runs.find(run => run.id === nativeSelectionRef.current);
            const latest = runs[0]?.state === 'running' ? runs[0] : runs.find(run => Array.isArray(run.result?.output_files) && run.result.output_files.length) ?? runs[0];
            if (selected || latest) setRunId((selected || latest)!.id);
          }
          if (!controller.signal.aborted && (streamWorking || backgroundWorking || runs.some(run => run.state === 'running'))) timer = setTimeout(refresh, 2000);
        }
      } catch { /* Main conversation and task view retain their own errors. */ }
    };
    void refresh();
    return () => { controller.abort(); if(timer) clearTimeout(timer); };
  }, [skillId, sessionId, historyLoading, streamWorking, backgroundWorking]);

  useEffect(() => {
    if (!sessionId) return;
    const state: PersistedAssistantState = {
      input,
      selectedFiles,
      selectedFileNames,
      pendingMessage,
      draft, runId, invalidatedDraftId: invalidDraftRef.current || undefined
    };
    try {
      window.localStorage.setItem(
        `${CHAT_UI_STATE_PREFIX}:${sessionId}`,
        JSON.stringify(state)
      );
    } catch {
      // A full or restricted browser storage must not block the conversation.
    }
  }, [draft, input, pendingMessage, selectedFileNames, selectedFiles, sessionId, runId]);

  useEffect(() => {
    if (!conversations.some(item => item.preview === '新对话')) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void fetch('/api/platform/assistant/conversations', { cache: 'no-store', signal: controller.signal })
        .then(async response => {
          if (response.ok && !controller.signal.aborted) {
            const items = await response.json() as AssistantConversationSummary[];
            if (!controller.signal.aborted) setConversations(items.filter(item => belongsToSkillSession(item.session_id, skillId)));
          }
        }).catch(() => {});
    }, 10000);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [conversations]);

  async function refreshConversationList() {
    setHistoryListLoading(true);
    try {
      const response = await fetch('/api/platform/assistant/conversations', {
        cache: 'no-store'
      });
      if (!response.ok) throw new Error('历史会话加载失败。');
      setConversations(((await response.json()) as AssistantConversationSummary[]).filter(item => belongsToSkillSession(item.session_id, skillId)));
      setHistoryListError('');
    } catch (listError) {
      setHistoryListError(listError instanceof Error ? listError.message : '历史会话加载失败。');
    } finally {
      setHistoryListLoading(false);
    }
  }

  async function selectConversation(nextSessionId: string) {
    if (!nextSessionId || nextSessionId === sessionId || working || !belongsToSkillSession(nextSessionId, skillId)) return;
    setHistoryLoading(true);
    setError('');
    try {
      const response = await fetch(
        `/api/platform/assistant/conversations/${encodeURIComponent(nextSessionId)}`,
        { cache: 'no-store' }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '历史会话加载失败。'));
      const conversation = (await response.json()) as AssistantConversation;
      setSessionId(conversation.session_id);
      window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, conversation.session_id);
      setMessages(conversationMessages(conversation));
      const storedState = readPersistedAssistantState(conversation.session_id);
      setInput(typeof storedState?.input === 'string' ? storedState.input : '');
      setSelectedFiles(
        Array.isArray(storedState?.selectedFiles)
          ? storedState.selectedFiles.filter((item): item is string => typeof item === 'string')
          : []
      );
      setSelectedFileNames(
        isRecord(storedState?.selectedFileNames)
          ? Object.fromEntries(
              Object.entries(storedState.selectedFileNames).filter(
                ([key, value]) => typeof key === 'string' && typeof value === 'string'
              )
            )
          : {}
      );
      setPendingMessage(
        typeof storedState?.pendingMessage === 'string' ? storedState.pendingMessage : ''
      );
      setDraft(draftFromDetails({ draft: storedState?.draft }));
      setRunId(storedState?.runId || "");
      invalidDraftRef.current = storedState?.invalidatedDraftId || null;
      setHistorical(true);
      setHistoryCheckedAt(new Date().toISOString());
    } catch (conversationError) {
      setError(
        conversationError instanceof Error ? conversationError.message : '历史会话加载失败。'
      );
    } finally {
      setHistoryLoading(false);
    }
  }

  function startNewConversation() {
    if (working) return;
    turnControllerRef.current?.abort();
    setSessionId('');
    invalidDraftRef.current = null;
    window.localStorage.removeItem(CHAT_SESSION_STORAGE_KEY);
    setMessages([welcomeMessage]);
    setInput('');
    setSelectedFiles([]);
    setSelectedFileNames({});
    setDraft(null);
    setRunId('');
    setNativeRuns([]); nativeSelectionRef.current = '';
    setPendingMessage('');
    setToolMessage('');
    setError('');
    setHistorical(false);
    setHistoryCheckedAt('');
    setHistoryLoading(false);
  }

  useEffect(() => {
    const selected = new Set(selectedFiles);
    setSelectedFileNames((current) => {
      const next = Object.fromEntries(
        Object.entries(current).filter(([fileId]) => selected.has(fileId))
      );
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [selectedFiles]);

  function handleSelectedFileIdsChange(nextFileIds: string[]) {
    if (skillId && draft) { invalidDraftRef.current = draft.id; setDraft(null); setPendingMessage('材料已变更，请发送处理要求以更新执行方案。'); }
    setSelectedFiles((current) => {
      const next = new Set(nextFileIds);
      if (
        nextFileIds.length > MAX_SELECTED_FILES ||
        next.size !== nextFileIds.length ||
        nextFileIds.some((fileId) => typeof fileId !== 'string')
      ) {
        return current;
      }
      const dropsExistingSelection = current.some((fileId) => !next.has(fileId));
      if (dropsExistingSelection && nextFileIds.length >= current.length) return current;
      return [...nextFileIds];
    });
  }

  function handleFileNameChange(fileId: string, name: string | null) {
    setSelectedFileNames((current) => {
      const next = { ...current };
      if (name) next[fileId] = name;
      else delete next[fileId];
      return next;
    });
  }

  function removeSelectedFile(fileId: string) {
    if (skillId && draft) { invalidDraftRef.current = draft.id; setDraft(null); setPendingMessage('材料已变更，请发送处理要求以更新执行方案。'); }
    setSelectedFiles((current) => current.filter((item) => item !== fileId));
    setSelectedFileNames((current) => {
      const next = { ...current };
      delete next[fileId];
      return next;
    });
  }

  async function sendMessage(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const message = input.trim();
    if (
      !message ||
      !configured ||
      historyLoading ||
      working ||
      turnControllerRef.current
    ) {
      return;
    }

    const activeSessionId = sessionId || `${skillSessionPrefix(skillId)}${createClientId()}`;
    if (!sessionId) {
      setSessionId(activeSessionId);
      window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, activeSessionId);
    }
    const assistantId = createClientId();
    const messageCreatedAt = new Date().toISOString();
    setHistorical(false);
    setHistoryCheckedAt('');
    setMessages((current) => [
      ...current,
      { id: createClientId(), role: 'user', content: message, createdAt: messageCreatedAt },
      { id: assistantId, role: 'assistant', content: '', createdAt: messageCreatedAt }
    ]);
    setInput('');
    setDraft(null);
    setToolMessage('');
    setPendingMessage('');
    setError('');
    setWorking(true);
    const controller = new AbortController();
    turnControllerRef.current = controller;

    let resolveTurnReady!: () => void;
    turnReadyRef.current = new Promise<void>(resolve => { resolveTurnReady = resolve; });
    let response: Response;
    try {
      response = await fetch('/api/platform/assistant/turn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: activeSessionId,
          message,
          file_ids: selectedFiles,
          skill_id: skillId
        }),
        signal: controller.signal
      }).finally(resolveTurnReady);
    } catch {
      if (controller.signal.aborted) {
        setToolMessage('');
      } else {
        setError('AI 助手连接失败。');
        setToolMessage('');
      }
      setMessages((current) =>
        assistantMessage(current, assistantId, (content) => content || '这次请求没有完成。')
      );
      if (turnControllerRef.current === controller) turnControllerRef.current = null;
      setWorking(false);
      return;
    }

    if (!response.ok) {
      setError(await responseMessage(response, 'AI 助手处理失败。'));
      setToolMessage('');
      setMessages((current) =>
        assistantMessage(current, assistantId, (content) => content || '这次请求没有完成。')
      );
      if (turnControllerRef.current === controller) turnControllerRef.current = null;
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
          if (skillId?.startsWith('native--') && isRecord(event.details) && isRecord(event.details.run) && typeof event.details.run.id === 'string') setRunId(event.details.run.id);
          const nextDraft = draftFromDetails(event.details);
          const clarification = clarificationFromDetails(event.details);
          if (nextDraft) {
            setDraft(nextDraft);
            setMessages((current) =>
              assistantMessage(current, assistantId, (content) =>
                draftCompletionMessage(content, nextDraft.skill_name)
              )
            );
          }
          if (clarification) setPendingMessage(clarification);
          setToolMessage(
            event.isError
              ? '查询未完成。'
              : event.toolName === 'prepare_context'
                ? '正在生成回答…'
                : '平台数据已返回给 AI。'
            );
        }
        if (event.type === 'await_confirmation') {
          setPendingMessage(event.message);
          setToolMessage('');
        }
        if (event.type === 'error') {
          setToolMessage('');
          setError(event.message);
          setMessages((current) =>
            assistantMessage(current, assistantId, (content) => content || event.message)
          );
        }
        if (event.type === 'done') setToolMessage('');
      });
      setToolMessage('');
    } catch (streamError) {
      setToolMessage('');
      if (controller.signal.aborted) {
        setMessages((current) =>
          assistantMessage(current, assistantId, (content) => content || '已停止生成。')
        );
      } else {
        const messageText =
          streamError instanceof Error ? streamError.message : 'AI 助手处理失败。';
        setError(messageText);
        setMessages((current) =>
          assistantMessage(current, assistantId, (content) => content || messageText)
        );
      }
    }
    if (controller.signal.aborted) {
      setToolMessage('');
      setMessages((current) =>
        assistantMessage(current, assistantId, (content) => content || '已停止生成。')
      );
    }
    if (turnControllerRef.current === controller) turnControllerRef.current = null;
    setWorking(false);
    void refreshConversationList();
  }

  async function stopMessage() {
    if (!sessionId) return;
    setToolMessage('正在停止…');
    try {
      await turnReadyRef.current;
      const response = await fetch('/api/platform/assistant/turn', {
        method: 'DELETE', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      });
      if (!response.ok) throw new Error(await responseMessage(response, '停止生成失败。'));
      turnControllerRef.current?.abort();
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : '停止生成失败。');
    }
  }

  async function openTaskWizard() {
    if (skillId && draft) {
      if (startingRun) return;
      setStartingRun(true);
      setError('');
      try {
        const response = await fetch(`/api/platform/task-drafts/${encodeURIComponent(draft.id)}/confirm`, { method: 'POST' });
        if (!response.ok) throw new Error(await responseMessage(response, '任务启动失败。'));
        const run = await response.json();
        setRunId(run.id);
        setDraft({ ...draft, state: 'consumed' });
      } catch (error) { setError(error instanceof Error ? error.message : '任务启动失败。'); }
      finally { setStartingRun(false); }
      return;
    }
    if (!draft) return;
    router.push(
      `/dashboard/skills/${encodeURIComponent(draft.skill_id)}/run?draft=${encodeURIComponent(draft.id)}`
    );
  }

  async function saveProfile(
    nextConnectionId: string,
    nextModel: string
  ): Promise<AdminAssistantProfile> {
    const response = await fetch('/api/platform/admin/assistant-profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ connection_id: nextConnectionId, model: nextModel })
    });
    if (!response.ok) {
      throw new Error(await responseMessage(response, '配置保存失败。'));
    }
    const saved = (await response.json()) as AdminAssistantProfile;
    setConfigured(true);
    return saved;
  }

  const selectedNames = selectedFiles.map(
    (fileId) => selectedFileNames[fileId] || `文件 ${fileId.slice(0, 8)}`
  );
  const hasContext =
    selectedNames.length > 0 ||
    Boolean(pendingMessage) ||
    Boolean(draft);
  const notice = !configured ? (
    <Alert variant='destructive'>
      <Icons.warning />
      <AlertTitle>AI 助手尚未配置</AlertTitle>
      <AlertDescription>
        {isAdmin ? '请在顶部选择一个已连接的模型。' : '请联系管理员配置部门默认模型。'}
      </AlertDescription>
    </Alert>
  ) : null;
  const conversationControls = (
    <div className='flex min-w-0 max-w-full flex-wrap items-center gap-2'>
      <Button
        type='button'
        size='sm'
        variant='outline'
        onClick={startNewConversation}
        disabled={working || historyLoading}
      >
        新对话
      </Button>
      <label className='sr-only' htmlFor='assistant-conversation-history'>
        切换历史会话
      </label>
      <label className='platform-control-target min-w-0 max-w-full'>
      <select
        id='assistant-conversation-history'
        value={sessionId}
        disabled={working || historyLoading || historyListLoading}
        onChange={(event) => void selectConversation(event.target.value)}
        className='min-h-11 min-w-0 max-w-full rounded-lg border bg-background px-2 text-sm sm:max-w-64 md:min-h-9'
      >
        <option value=''>当前新对话</option>
        {conversations.map((conversation) => (
          <option key={conversation.session_id} value={conversation.session_id}>
            {conversation.preview || '新对话'}
          </option>
        ))}
      </select>
      </label>
      {historyListLoading && <span className='text-xs text-muted-foreground'>读取历史中…</span>}
      {historyListError && (
        <button
          type='button'
          className='platform-action text-sm text-destructive underline-offset-4 hover:underline'
          onClick={() => void refreshConversationList()}
        >
          历史读取失败，重试
        </button>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
    <AssistantShell
      header={
        <AssistantHeader
          conversationControls={conversationControls}
          modelSelector={
            <AssistantModelSelector
              isAdmin={isAdmin}
              initialModel={initialModel}
              profile={profile}
              connections={connections}
              onSave={saveProfile}
            />
          }
        />
      }
      notice={notice}
      transcript={
        <AssistantTranscript
          messages={messages}
          historical={historical}
          checkedAt={historyCheckedAt}
        />
      }
      composer={
        <AssistantComposer
          skillId={skillId}
          fileInputs={fileInputs}
          onUploadWorkingChange={setUploadWorking}
          configured={configured}
          historyLoading={historyLoading}
          working={working}
          input={input}
          selectedFileIds={selectedFiles}
          selectedFileNames={selectedFileNames}
          error={error}
          onInputChange={setInput}
          onSubmit={(event) => void sendMessage(event)}
          onStop={stopMessage}
          onSelectedFileIdsChange={handleSelectedFileIdsChange}
          onFileNameChange={handleFileNameChange}
          onRemoveFile={removeSelectedFile}
        />
      }
      context={
        hasContext ? (
          <AssistantContextPanel
            selectedFileNames={selectedNames}
            pendingMessage={pendingMessage}
            draft={draft}
            onOpenTask={() => void openTaskWizard()}
            executeInPlace={Boolean(skillId)}
            startingRun={working}
            selectedFileNamesById={selectedFileNames}
          />
        ) : undefined
      }
    />
    {nativeRuns.length > 1 && <label className="flex flex-wrap items-center gap-2 text-sm">本会话执行记录<select aria-label="本会话执行记录" value={runId} onChange={event => {nativeSelectionRef.current = event.target.value; setRunId(event.target.value);}} className="rounded-md border border-input bg-background px-3 py-2 text-foreground">{nativeRuns.map((run,index) => <option key={run.id} value={run.id}>第 {nativeRuns.length-index} 次 · {run.state === 'succeeded' ? '已完成' : run.state === 'running' ? '执行中' : '未完成'}</option>)}</select></label>}
    {runId && <section aria-label="本次任务结果"><Suspense fallback={<p>正在读取任务进度…</p>}><RunDetailView key={runId} runId={runId} /></Suspense></section>}
    </div>
  );
}
