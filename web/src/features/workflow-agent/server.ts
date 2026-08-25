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
  PlatformSession,
  WorkflowAgentContext,
  WorkflowRead
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SESSION_ID = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_SESSIONS = 100;
const WORKFLOW_ACTIONS_BY_STAGE: Record<string, readonly string[]> = {
  awaiting_date: ['set_reconciliation_date', 'get_workflow_stage'],
  awaiting_date_confirmation: [
    'set_reconciliation_date',
    'get_workflow_stage',
    'request_user_confirmation'
  ],
  awaiting_files: ['set_reconciliation_date', 'get_workflow_stage', 'prepare_daily_reconciliation'],
  preparing: ['get_workflow_stage'],
  awaiting_apply_confirmation: [
    'get_workflow_stage',
    'request_regeneration',
    'request_user_confirmation'
  ],
  applying: ['get_workflow_stage'],
  completed: ['get_workflow_stage'],
  failed: ['get_workflow_stage', 'request_regeneration'],
  cancelled: ['get_workflow_stage']
};

interface WorkflowTurnInput {
  workflowId: string;
  sessionId: string;
  message: string;
}

interface WorkflowActionResponse {
  workflow: WorkflowRead;
  action: string;
  await_confirmation: boolean;
  confirmation_kind: '' | 'date' | 'apply';
  message: string;
}

interface RuntimeEntry {
  ownerId: string;
  runtime: PiAgentRuntime;
  model: ReturnType<typeof createPlatformModel>['model'];
  tokenRef: { value: string };
  lastUsed: number;
}

interface WorkflowTurnStream {
  events: AsyncIterable<AgentEvent>;
  abort: () => void;
}

const sessions = new Map<string, RuntimeEntry>();

function checkedInput(input: WorkflowTurnInput): WorkflowTurnInput {
  if (!UUID.test(input.workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
  if (!SESSION_ID.test(input.sessionId)) throw new PlatformApiError(400, 'AI 会话标识格式无效。');
  const message = input.message.trim();
  if (!message || message.length > 4000) {
    throw new PlatformApiError(400, '工作流 Agent 消息必须为 1 到 4000 个字符。');
  }
  return { ...input, message };
}

function sessionKey(ownerId: string, workflowId: string, sessionId: string): string {
  return `${ownerId}:${workflowId}:${sessionId}`;
}

function touchSession(key: string, entry: RuntimeEntry): void {
  entry.lastUsed = Date.now();
  sessions.delete(key);
  sessions.set(key, entry);
  while (sessions.size > MAX_SESSIONS) {
    const oldest = sessions.keys().next().value;
    if (typeof oldest !== 'string') break;
    sessions.delete(oldest);
  }
}

function textResult(text: string, details: Record<string, unknown> = {}) {
  return {
    content: [{ type: 'text' as const, text }],
    details
  };
}

function workflowSummary(workflow: WorkflowRead): string {
  return JSON.stringify(
    {
      id: workflow.id,
      display_id: workflow.display_id,
      skill_id: workflow.skill_id,
      stage: workflow.stage,
      state: workflow.state,
      reconciliation_date: workflow.reconciliation_date,
      progress: workflow.progress,
      progress_message: workflow.progress_message,
      error_message: workflow.error_message
    },
    null,
    2
  );
}

async function currentWorkflow(workflowId: string): Promise<WorkflowRead> {
  return platformServerRequest<WorkflowRead>(`/api/workflows/${workflowId}`);
}

async function workflowContext(workflowId: string): Promise<WorkflowAgentContext> {
  return platformServerRequest<WorkflowAgentContext>(`/api/workflows/${workflowId}/agent/context`);
}

async function requestWorkflowAction(
  workflowId: string,
  action: string,
  args: Record<string, unknown>
): Promise<WorkflowActionResponse> {
  return platformServerRequest<WorkflowActionResponse>(
    `/api/workflows/${workflowId}/agent/actions`,
    {
      method: 'POST',
      body: JSON.stringify({ action, arguments: args })
    }
  );
}

function actionResult(response: WorkflowActionResponse) {
  return textResult(response.message || workflowSummary(response.workflow), {
    workflow: response.workflow,
    action: response.action,
    awaitConfirmation: response.await_confirmation,
    confirmationKind: response.confirmation_kind,
    confirmationMessage: response.message
  });
}

function createWorkflowTools(workflowId: string, stage: string): AgentTool[] {
  const getStage: AgentTool = {
    name: 'get_workflow_stage',
    label: '查询工作流阶段',
    description: '读取当前工作流阶段和进度，不执行任何动作。',
    parameters: Type.Object({}),
    execute: async () => {
      const workflow = await currentWorkflow(workflowId);
      return textResult(workflowSummary(workflow), { workflow });
    }
  };

  const setDate: AgentTool = {
    name: 'set_reconciliation_date',
    label: '设置核销日期',
    description: '请求平台设置核销日期；不会运行 Worker 或写入文件。',
    parameters: Type.Object({
      date: Type.String({ pattern: '^\\d{4}-\\d{2}-\\d{2}$' })
    }),
    execute: async (_toolCallId, params) =>
      actionResult(
        await requestWorkflowAction(
          workflowId,
          'set_reconciliation_date',
          params as Record<string, unknown>
        )
      )
  };

  const prepare: AgentTool = {
    name: 'prepare_daily_reconciliation',
    label: '准备核销日清',
    description: '请求平台排队准备日清；实际脚本仍由现有 Workflow Worker 执行。',
    parameters: Type.Object({}),
    execute: async () =>
      actionResult(await requestWorkflowAction(workflowId, 'prepare_daily_reconciliation', {}))
  };

  const regenerate: AgentTool = {
    name: 'request_regeneration',
    label: '请求重新生成',
    description: '请求平台重新生成日清预览，不直接访问文件或执行脚本。',
    parameters: Type.Object({
      reason: Type.Optional(Type.String({ maxLength: 1000 }))
    }),
    execute: async (_toolCallId, params) =>
      actionResult(
        await requestWorkflowAction(
          workflowId,
          'request_regeneration',
          params as Record<string, unknown>
        )
      )
  };

  const confirmation: AgentTool = {
    name: 'request_user_confirmation',
    label: '请求用户确认',
    description: '请求前端展示日期或写入预览确认，不代表用户已经确认。',
    parameters: Type.Object({
      kind: Type.Union([Type.Literal('date'), Type.Literal('apply')]),
      message: Type.Optional(Type.String({ maxLength: 1000 }))
    }),
    execute: async (_toolCallId, params) =>
      actionResult(
        await requestWorkflowAction(
          workflowId,
          'request_user_confirmation',
          params as Record<string, unknown>
        )
      )
  };

  const tools = new Map([
    [setDate.name, setDate],
    [getStage.name, getStage],
    [prepare.name, prepare],
    [regenerate.name, regenerate],
    [confirmation.name, confirmation]
  ]);
  return (WORKFLOW_ACTIONS_BY_STAGE[stage] ?? ['get_workflow_stage'])
    .map((action) => tools.get(action))
    .filter((tool): tool is AgentTool => Boolean(tool));
}

function systemPrompt(workflow: WorkflowRead): string {
  return [
    '你是财务平台的工作流 Agent，只负责解释当前阶段并请求受控动作。',
    '你不能运行命令、访问本地路径、读取凭据、读取或写入工作簿，也不能调用智云或其他外部服务。',
    '你只能请求提供的五个受控动作；实际处理由 Python Workflow 和后台 Worker 完成。',
    '请求用户确认不等于用户已经确认；只有用户明确确认后，平台硬闸才允许后续动作。',
    `当前工作流：${workflowSummary(workflow)}`
  ].join('\n');
}

async function* legacyTurn(input: WorkflowTurnInput): AsyncIterable<AgentEvent> {
  const workflow = await platformServerRequest<WorkflowRead>(
    `/api/workflows/${input.workflowId}/messages`,
    { method: 'POST', body: JSON.stringify({ content: input.message }) }
  );
  yield { type: 'tool_start', toolCallId: 'legacy-workflow', toolName: 'legacy_workflow_message' };
  yield {
    type: 'tool_result',
    toolCallId: 'legacy-workflow',
    toolName: 'legacy_workflow_message',
    isError: false,
    awaitConfirmation:
      workflow.stage === 'awaiting_date_confirmation' ||
      workflow.stage === 'awaiting_apply_confirmation',
    details: { workflow }
  };
  yield { type: 'done', messageCount: workflow.messages.length };
}

function getOrCreateRuntime(
  ownerId: string,
  workflow: WorkflowAgentContext & { connection_id: string; model: string },
  sessionId: string,
  token: string
): { entry: RuntimeEntry; key: string } {
  const key = sessionKey(ownerId, workflow.workflow.id, sessionId);
  const existing = sessions.get(key);
  if (existing) {
    existing.tokenRef.value = token;
    touchSession(key, existing);
    return { entry: existing, key };
  }

  const tokenRef = { value: token };
  const modelHandle = createPlatformModel({
    modelId: workflow.model,
    gatewayUrl: `${platformServerBaseUrl()}/api/assistant/model`,
    accessToken: async () => tokenRef.value,
    gatewayFields: { connection_id: workflow.connection_id }
  });
  const entry: RuntimeEntry = {
    ownerId,
    runtime: new PiAgentRuntime({ streamFn: modelHandle.streamSimple }),
    model: modelHandle.model,
    tokenRef,
    lastUsed: Date.now()
  };
  touchSession(key, entry);
  return { entry, key };
}

export async function createWorkflowAgentTurn(
  input: WorkflowTurnInput
): Promise<WorkflowTurnStream> {
  const checked = checkedInput(input);
  const credential = await platformCredential();
  const token = runtimeAccessToken(credential);
  const clerkUserId = credential.clerkUserId;

  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (resolveAgentRuntime(runtimeSelectorId(clerkUserId, session.user_id)) === 'legacy') {
    return { events: legacyTurn(checked), abort: () => undefined };
  }

  const context = await workflowContext(checked.workflowId);
  const workflow = context.workflow;
  const connectionId = context.connection_id;
  const model = context.model;
  if (!connectionId || !model) {
    // 表单启动的后台任务由确定性 Worker 处理，不应把兼容标记当作
    // model_connections ID 再次送进模型网关。
    return { events: legacyTurn(checked), abort: () => undefined };
  }
  const agentContext: WorkflowAgentContext & { connection_id: string; model: string } = {
    ...context,
    connection_id: connectionId,
    model
  };
  const { entry, key } = getOrCreateRuntime(
    session.user_id,
    agentContext,
    checked.sessionId,
    token
  );
  entry.tokenRef.value = token;
  const turn = entry.runtime.startTurn({
    sessionId: key,
    ownerId: session.user_id,
    model: entry.model,
    message: checked.message,
    systemPrompt: systemPrompt(workflow),
    tools: createWorkflowTools(workflow.id, workflow.stage)
  });
  return {
    events: withLegacyFallback(turn, () => legacyTurn(checked)),
    abort: () => entry.runtime.abort(key, session.user_id)
  };
}
