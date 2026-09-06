import 'server-only';

import { platformCredential, runtimeAccessToken } from '@/features/auth/server-auth';
import {
  type AgentEvent,
  type AgentTool,
  createPlatformModel,
  PiAgentRuntime
} from '@financial-platform/agent-runtime';
import { Type } from 'typebox';
import { PlatformApiError } from '@/features/platform-api/errors';
import { safeCatalog, type SafeSkill } from '@/features/ai-chat/safe-catalog';
import { createPlatformInformationTool } from '@/features/ai-chat/platform-information-tool';
import { listSelectableInputFilesByIds } from '@/features/files/api/server';
import {
  resolveAgentRuntime,
  runtimeSelectorId,
  withLegacyFallback
} from '@/features/ai-chat/runtime-mode';
import {
  platformServerBaseUrl,
  platformServerRequest
} from '@/features/platform-api/server-client';
import type {
  PlatformFileOption,
  PlatformSession,
  AssistantConversation,
  RunDetail,
  RunPage,
  WorkflowRead,
  SkillDetail,
  TaskDraft
} from '@/features/platform-api/types';

const MAX_SESSION_ENTRIES = 100;
const MAX_SELECTED_FILES = 20;
const SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/;

interface AssistantTurnInput {
  sessionId: string;
  message: string;
  fileIds: string[];
}

interface RecommendationArguments {
  skill_id: string;
  confidence: number;
  candidates?: string[];
  parameters: Record<string, unknown>;
  file_roles: Record<string, string | string[]>;
  clarification?: string;
  confirmation_text?: string;
}

interface RuntimeEntry {
  ownerId: string;
  runtime: PiAgentRuntime;
  model: ReturnType<typeof createPlatformModel>['model'];
  tokenRef: { value: string };
  lastUsed: number;
}

interface AssistantTurnStream {
  events: AsyncIterable<AgentEvent>;
  abort: () => void;
}

interface CacheEntry<T> {
  value?: T;
  expiresAt: number;
  pending?: Promise<T>;
}

type RunningTask = {
  id: string;
  display_id?: string;
  kind: '任务';
  skill_id: string;
  skill_name: string;
  state: string;
  stage?: string;
  progress: number;
  progress_message: string;
  current_step?: string;
  current_step_label?: string;
  error_message?: string;
};

async function* legacyTurn(input: AssistantTurnInput): AsyncIterable<AgentEvent> {
  const draft = await platformServerRequest<TaskDraft>('/api/assistant/prepare', {
    method: 'POST',
    body: JSON.stringify({ message: input.message, file_ids: input.fileIds })
  });
  yield { type: 'tool_start', toolCallId: 'legacy-prepare', toolName: 'prepare_task_draft' };
  yield {
    type: 'tool_result',
    toolCallId: 'legacy-prepare',
    toolName: 'prepare_task_draft',
    isError: false,
    awaitConfirmation: false,
    details: { draft }
  };
  yield { type: 'done', messageCount: 0 };
}

const sessions = new Map<string, RuntimeEntry>();
const skillCache = new Map<string, CacheEntry<SkillDetail[]>>();
const taskCache = new Map<string, CacheEntry<RunningTask[]>>();

async function cached<T>(
  cache: Map<string, CacheEntry<T>>,
  key: string,
  ttlMs: number,
  loader: () => Promise<T>
): Promise<T> {
  const current = cache.get(key);
  if (current?.value !== undefined && current.expiresAt > Date.now()) return current.value;
  if (current?.pending) return current.pending;

  const pending = loader()
    .then((value) => {
      cache.set(key, { value, expiresAt: Date.now() + ttlMs });
      return value;
    })
    .catch((error) => {
      cache.delete(key);
      throw error;
    });
  cache.set(key, { expiresAt: 0, pending });
  return pending;
}

function checkedInput(input: AssistantTurnInput): AssistantTurnInput {
  if (!SESSION_ID.test(input.sessionId)) {
    throw new PlatformApiError(400, 'AI 会话标识格式无效。');
  }
  const message = input.message.trim();
  if (!message || message.length > 4000) {
    throw new PlatformApiError(400, '任务描述必须为 1 到 4000 个字符。');
  }
  if (
    input.fileIds.length > MAX_SELECTED_FILES ||
    input.fileIds.some((item) => typeof item !== 'string')
  ) {
    throw new PlatformApiError(400, '所选文件标识无效。');
  }
  return { ...input, message };
}

function fileCatalog(files: PlatformFileOption[], selectedIds: string[]) {
  const byId = new Map(files.map((file) => [file.id, file]));
  return selectedIds.flatMap((fileId, index) => {
    const file = byId.get(fileId);
    if (!file) return [];
    return [
      {
        alias: `F${index + 1}`,
        name: file.name,
        size_bytes: file.size_bytes
      }
    ];
  });
}

function runningTaskSummary(runs: RunPage, workflows: WorkflowRead[]): RunningTask[] {
  const tasks: RunningTask[] = [];
  for (const run of runs.items ?? []) {
    if (['succeeded', 'failed', 'timed_out', 'cancelled'].includes(run.state)) continue;
    tasks.push({
      id: run.id,
      kind: '任务',
      skill_id: run.skill_id,
      skill_name: run.skill_name,
      state: run.state,
      progress: run.progress,
      progress_message: run.progress_message,
      error_message: run.error_message || undefined
    });
  }
  for (const workflow of workflows ?? []) {
    if (['succeeded', 'failed', 'cancelled'].includes(workflow.state)) continue;
    tasks.push({
      id: workflow.id,
      display_id: workflow.display_id,
      kind: '任务',
      skill_id: workflow.skill_id,
      skill_name: workflow.skill_name,
      state: workflow.state,
      stage: workflow.stage,
      progress: workflow.progress,
      progress_message: workflow.progress_message,
      current_step: workflow.current_step,
      current_step_label: workflow.current_step_label,
      error_message: workflow.error_message || undefined
    });
  }
  return tasks.toSorted((left, right) => right.progress - left.progress).slice(0, 100);
}

function runTaskSummary(run: RunDetail): RunningTask {
  return {
    id: run.id,
    kind: '任务',
    skill_id: run.skill_id,
    skill_name: run.skill_name,
    state: run.state,
    progress: run.progress,
    progress_message: run.progress_message,
    error_message: run.error_message || undefined
  };
}

function workflowTaskSummary(workflow: WorkflowRead): RunningTask {
  return {
    id: workflow.id,
    display_id: workflow.display_id,
    kind: '任务',
    skill_id: workflow.skill_id,
    skill_name: workflow.skill_name,
    state: workflow.state,
    stage: workflow.stage,
    progress: workflow.progress,
    progress_message: workflow.progress_message,
    current_step: workflow.current_step,
    current_step_label: workflow.current_step_label,
    error_message: workflow.error_message || undefined
  };
}

async function listRunningTasks(): Promise<RunningTask[]> {
  const [runs, workflows] = await Promise.all([
    platformServerRequest<RunPage>('/api/runs?page=1&page_size=100'),
    platformServerRequest<WorkflowRead[]>('/api/workflows?limit=100')
  ]);
  return runningTaskSummary(runs, workflows);
}

async function findTask(taskId: string): Promise<RunningTask | null> {
  try {
    return runTaskSummary(
      await platformServerRequest<RunDetail>(`/api/runs/${encodeURIComponent(taskId)}`)
    );
  } catch {
    // The same task-status tool also supports guided workflow sessions.
  }
  try {
    return workflowTaskSummary(
      await platformServerRequest<WorkflowRead>(`/api/workflows/${encodeURIComponent(taskId)}`)
    );
  } catch {
    return null;
  }
}

function jsonText(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function textResult(text: string, details: Record<string, unknown> = {}) {
  return {
    content: [{ type: 'text' as const, text }],
    details
  };
}

function createTools(
  skills: SafeSkill[],
  input: AssistantTurnInput,
  role: PlatformSession['role']
): AgentTool[] {
  const platformInformationTool = createPlatformInformationTool(role, (path) =>
    platformServerRequest<unknown>(path)
  );
  const listTool: AgentTool = {
    name: 'list_authorized_skills',
    label: '查询可用 Skill',
    description: '查询当前 Platform User 可以创建草稿的只读 Skill。',
    parameters: Type.Object({}),
    execute: async () =>
      textResult(
        jsonText(
          skills.map(({ id, name, description, version, file_inputs }) => ({
            id,
            name,
            description,
            version,
            file_inputs
          }))
        ),
        { skills }
      )
  };

  const recommendTool: AgentTool = {
    name: 'recommend_skill',
    label: '推荐 Skill',
    description: '从授权目录中确认一个候选 Skill，不会创建任务或执行操作。',
    parameters: Type.Object({
      skill_id: Type.String(),
      confidence: Type.Number({ minimum: 0, maximum: 1 }),
      reason: Type.String({ maxLength: 1000 })
    }),
    execute: async (_toolCallId, params) => {
      const value = params as { skill_id: string; confidence: number; reason: string };
      const skill = skills.find((item) => item.id === value.skill_id);
      if (!skill) throw new Error('模型推荐了当前会话未授权的 Skill。');
      return textResult(
        `候选 Skill：${skill.name}（${skill.id}），置信度 ${Math.round(value.confidence * 100)}%。`,
        { skill, reason: value.reason }
      );
    }
  };

  const prepareTool: AgentTool = {
    name: 'prepare_task_draft',
    label: '生成任务草稿',
    description: '根据授权 Skill、用户参数和已选文件生成不可执行任务草稿。',
    parameters: Type.Object({
      skill_id: Type.String({ description: '只能填写授权 Skill 目录中的 id。' }),
      confidence: Type.Number({ minimum: 0, maximum: 1 }),
      candidates: Type.Optional(Type.Array(Type.String(), { maxItems: 3 })),
      parameters: Type.Record(Type.String(), Type.Unknown()),
      file_roles: Type.Record(
        Type.String(),
        Type.Union([Type.String(), Type.Array(Type.String())])
      ),
      clarification: Type.Optional(Type.String({ maxLength: 1000 })),
      confirmation_text: Type.Optional(Type.String({ maxLength: 1000 }))
    }),
    execute: async (_toolCallId, params) => {
      const recommendation = params as RecommendationArguments;
      if (!skills.some((skill) => skill.id === recommendation.skill_id)) {
        throw new Error('模型推荐了当前会话未授权的 Skill。');
      }
      const draft = await platformServerRequest<TaskDraft>(
        '/api/assistant/prepare-from-recommendation',
        {
          method: 'POST',
          body: JSON.stringify({
            message: input.message,
            file_ids: input.fileIds,
            recommendation
          })
        }
      );
      return textResult(`任务草稿已生成：${draft.skill_name}（${draft.state}）。`, { draft });
    }
  };

  const statusTool: AgentTool = {
    name: 'get_task_status',
    label: '查询任务状态',
    description: '查询当前用户有权访问的任务状态，不会启动或修改任务。',
    parameters: Type.Object({ task_id: Type.String({ minLength: 1, maxLength: 64 }) }),
    execute: async (_toolCallId, params) => {
      const taskId = (params as { task_id: string }).task_id;
      const task = await findTask(taskId);
      if (!task) throw new Error('当前账号没有找到这个任务。');
      return textResult(
        `${task.kind} ${task.display_id ?? task.id} 当前状态：${task.state}，进度 ${task.progress}%，${task.progress_message}。`,
        { task }
      );
    }
  };

  const runningTasksTool: AgentTool = {
    name: 'list_running_tasks',
    label: '查询运行中的任务',
    description: '查看当前账号可见的全部进行中任务，只读。',
    parameters: Type.Object({}),
    execute: async () => {
      const tasks = await listRunningTasks();
      const displayTasks = tasks.map(({ id, display_id: displayId, ...task }) => ({
        ...task,
        task_id: displayId ?? id
      }));
      return textResult(tasks.length ? jsonText(displayTasks) : '当前没有正在运行的任务。', {
        tasks
      });
    }
  };

  const clarificationTool: AgentTool = {
    name: 'request_clarification',
    label: '请求补充信息',
    description: '当任务参数或文件不足时向用户提出一个明确的问题。',
    parameters: Type.Object({ question: Type.String({ minLength: 1, maxLength: 1000 }) }),
    execute: async (_toolCallId, params) => {
      const question = (params as { question: string }).question.trim();
      if (!question) throw new Error('补充信息问题不能为空。');
      return textResult(question, { clarification: question });
    }
  };

  return [
    platformInformationTool,
    listTool,
    recommendTool,
    prepareTool,
    statusTool,
    runningTasksTool,
    clarificationTool
  ];
}

function systemPrompt(
  skills: SafeSkill[],
  files: ReturnType<typeof fileCatalog>,
  runningTasks: RunningTask[],
  history: AssistantConversation | null
): string {
  const historyItems = (history?.messages ?? [])
    .filter((item) => item.role === 'user' || item.role === 'assistant')
    .slice(-20)
    .map((item) => ({ role: item.role, content: item.content.slice(0, 4000) }));
  return [
    '你是财务平台的 AI 助手，可以像正常大模型一样回答问题、解释业务、总结任务状态并协助用户规划财务工作。',
    '回答使用简洁、自然的 Markdown。短回答直接写段落；只有确有层级或并列关系时才使用标题、列表或表格，避免堆叠格式。',
    '你不能访问本地路径、运行命令、读取凭据或直接写入文件。真实 Skill 任务只能由平台任务执行器运行。',
    '用户询问平台中的业务信息时，调用 query_platform_information。它可以按需读取当前登录账号有权查看的工作台、Skill、任务、文件元数据、工作流、提醒和个人资料；管理员还可以读取管理页面信息。不能声称能看到账号权限以外的数据。',
    'query_platform_information 不提供密码、API Key、会话令牌、服务凭据、文件正文或本地路径；不要向用户索要这些内容。列表较长时按页查询并说明当前页范围。',
    '用户询问正在运行、排队、失败或完成的任务时，优先调用 list_running_tasks 或 get_task_status，不要猜测状态。',
    '需要创建标准只读任务时，才能从授权目录中选择 Skill，并通过 prepare_task_draft 生成草稿；不能绕过平台校验直接执行。',
    '文件只能使用下方 file_catalog 中的 alias，不能猜测文件 ID 或路径。',
    '涉及金额、明细或结果时，只能依据工具返回的数据，不要编造数字。',
    `authorized_skill_catalog: ${jsonText(skills)}`,
    `file_catalog: ${jsonText(files)}`,
    `当前可见的运行任务: ${jsonText(runningTasks)}`,
    `此前对话记录: ${jsonText(historyItems)}`
  ].join('\n');
}

function sessionKey(ownerId: string, sessionId: string): string {
  return `${ownerId}:${sessionId}`;
}

function touchSession(key: string, entry: RuntimeEntry): void {
  entry.lastUsed = Date.now();
  sessions.delete(key);
  sessions.set(key, entry);
  while (sessions.size > MAX_SESSION_ENTRIES) {
    const oldest = sessions.keys().next().value;
    if (typeof oldest !== 'string') break;
    sessions.delete(oldest);
  }
}

function getOrCreateRuntime(
  ownerId: string,
  sessionId: string,
  token: string
): { entry: RuntimeEntry; tokenRef: { value: string }; created: boolean } {
  const key = sessionKey(ownerId, sessionId);
  const existing = sessions.get(key);
  if (existing) {
    existing.tokenRef.value = token;
    touchSession(key, existing);
    return { entry: existing, tokenRef: existing.tokenRef, created: false };
  }

  const tokenRef = { value: token };
  const modelHandle = createPlatformModel({
    modelId: 'financial-platform-assistant',
    gatewayUrl: `${platformServerBaseUrl()}/api/assistant/model`,
    accessToken: async () => tokenRef.value
  });
  const entry: RuntimeEntry = {
    ownerId,
    runtime: new PiAgentRuntime({ streamFn: modelHandle.streamSimple }),
    model: modelHandle.model,
    tokenRef,
    lastUsed: Date.now()
  };
  touchSession(key, entry);
  return { entry, tokenRef, created: true };
}

export async function createAssistantTurn(input: AssistantTurnInput): Promise<AssistantTurnStream> {
  const checked = checkedInput(input);
  const credential = await platformCredential();
  const token = runtimeAccessToken(credential);
  const clerkUserId = credential.clerkUserId;

  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (resolveAgentRuntime(runtimeSelectorId(clerkUserId, session.user_id)) === 'legacy') {
    return { events: legacyTurn(checked), abort: () => undefined };
  }

  const { entry, tokenRef, created } = getOrCreateRuntime(
    session.user_id,
    checked.sessionId,
    token
  );
  tokenRef.value = token;

  async function* events(): AsyncIterable<AgentEvent> {
    // 先把可见状态告诉前端，避免上下文查询期间页面看起来像卡死。
    yield { type: 'tool_start', toolCallId: 'assistant-context', toolName: 'prepare_context' };
    const selectedFileIds = [...checked.fileIds].sort();
    const availableFilesPromise = selectedFileIds.length
      ? listSelectableInputFilesByIds(selectedFileIds)
      : Promise.resolve<PlatformFileOption[]>([]);
    const [skills, availableFiles, runningTasks, history] = await Promise.all([
      cached(skillCache, session.user_id, 30_000, () =>
        platformServerRequest<SkillDetail[]>('/api/assistant/skills')
      ),
      availableFilesPromise,
      cached(taskCache, session.user_id, 5_000, listRunningTasks),
      created
        ? platformServerRequest<AssistantConversation>(
            `/api/assistant/conversations/${encodeURIComponent(checked.sessionId)}`
          ).catch(() => null)
        : Promise.resolve(null)
    ]);
    const safeSkills = safeCatalog(skills);
    yield {
      type: 'tool_result',
      toolCallId: 'assistant-context',
      toolName: 'prepare_context',
      isError: false,
      awaitConfirmation: false,
      details: {}
    };
    const turn = entry.runtime.startTurn({
      sessionId: checked.sessionId,
      ownerId: session.user_id,
      model: entry.model,
      message: checked.message,
      systemPrompt: systemPrompt(
        safeSkills,
        fileCatalog(availableFiles, checked.fileIds),
        runningTasks,
        history
      ),
      tools: createTools(safeSkills, checked, session.role)
    });
    yield* withLegacyFallback(turn, () => legacyTurn(checked));
  }
  return {
    events: events(),
    abort: () => entry.runtime.abort(checked.sessionId, session.user_id)
  };
}
