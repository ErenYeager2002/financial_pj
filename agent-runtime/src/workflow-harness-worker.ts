import os from 'node:os';
import process from 'node:process';

import type { AgentTool } from '@earendil-works/pi-agent-core';
import { Type } from 'typebox';

import { createPlatformModel } from './platform-model-adapter.js';
import { PiAgentRuntime } from './pi-agent-adapter.js';

interface HarnessWorkflow {
  workflow_id: string;
  state: string;
  stage: string;
  reconciliation_date: string;
  batch_id: string | null;
  batch_sequence: number | null;
  progress: number;
  progress_message: string;
  error_message: string;
  skill: Record<string, unknown>;
  model: Record<string, unknown>;
  material: Record<string, unknown>;
  files: Record<string, unknown>;
  artifacts: unknown[];
  context: Record<string, unknown>;
  messages: unknown[];
  actions: unknown[];
  batch: Record<string, unknown> | null;
}

interface DeclaredTool {
  name: string;
  description: string;
  required_arguments: string[];
}

interface HarnessClaim {
  action_id: string;
  workflow: HarnessWorkflow;
  skill: {
    id: string;
    version: string;
    hash: string;
    instructions: string;
    tools: DeclaredTool[];
  };
  model: string;
}

interface ToolResponse {
  action_id: string | null;
  state: string;
  error_message?: string;
  workflow: HarnessWorkflow;
  data?: unknown;
}

const apiBase = requiredEnvironment('FINANCIAL_PLATFORM_API_URL').replace(/\/$/, '');
const token = requiredEnvironment('FINANCIAL_PI_HARNESS_TOKEN');
const workerId = `${os.hostname()}:${process.pid}`;
const pollMilliseconds = positiveInteger('FINANCIAL_PI_HARNESS_POLL_MS', 1000);
let stopping = false;

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

function positiveInteger(name: string, fallback: number): number {
  const parsed = Number(process.env[name]);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  if (init.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  const payload = (await response.json().catch(() => null)) as Record<string, unknown> | null;
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string' ? payload.detail : '平台请求失败。';
    throw new Error(detail);
  }
  return payload as T;
}

async function heartbeat(actionId: string): Promise<void> {
  await apiRequest(`/api/internal/pi-harness/actions/${encodeURIComponent(actionId)}/heartbeat`, {
    method: 'POST',
    body: JSON.stringify({ worker_id: workerId })
  });
}

async function waitForTool(
  workflowId: string,
  actionId: string,
  harnessActionId: string
): Promise<ToolResponse> {
  while (!stopping) {
    await heartbeat(harnessActionId);
    const result = await apiRequest<ToolResponse>(
      `/api/internal/pi-harness/workflows/${encodeURIComponent(workflowId)}/actions/${encodeURIComponent(actionId)}?worker_id=${encodeURIComponent(workerId)}`
    );
    if (result.state === 'succeeded') return result;
    if (result.state === 'failed') {
      throw new Error(result.error_message || '受控工具执行失败。');
    }
    if (!['queued', 'running'].includes(result.state)) {
      throw new Error(result.error_message || `受控工具已停止：${result.state}`);
    }
    await delay(pollMilliseconds);
  }
  throw new Error('Pi Harness Worker 正在停止。');
}

function toolParameters(tool: DeclaredTool) {
  if (tool.name === 'read_task_file') {
    return Type.Object(
      {
        path: Type.String({ minLength: 1 }),
        offset: Type.Optional(Type.Integer({ minimum: 0 })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50_000 }))
      },
      { additionalProperties: false }
    );
  }
  if (tool.name === 'inspect_fetched_data') {
    return Type.Object(
      {
        offset: Type.Optional(Type.Integer({ minimum: 0 })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 }))
      },
      { additionalProperties: false }
    );
  }
  if (tool.name !== 'apply_reconciliation') return Type.Object({});
  return Type.Object(
    {
      reconciliation_date: Type.String({ pattern: '^\\d{4}-\\d{2}-\\d{2}$' }),
      material_set_id: Type.String({ minLength: 1 }),
      material_version: Type.Integer({ minimum: 1 }),
      plan_fingerprint: Type.String({ pattern: '^[a-f0-9]{64}$' })
    },
    { additionalProperties: false }
  );
}

function createHarnessTools(claim: HarnessClaim): AgentTool[] {
  return claim.skill.tools.map((declared) => ({
    name: declared.name,
    label: declared.name,
    description: declared.description,
    parameters: toolParameters(declared),
    executionMode: 'sequential' as const,
    execute: async (_toolCallId: string, parameters: unknown) => {
      const argumentsPayload =
        parameters && typeof parameters === 'object' && !Array.isArray(parameters)
          ? (parameters as Record<string, unknown>)
          : {};
      const queued = await apiRequest<ToolResponse>(
        `/api/internal/pi-harness/workflows/${encodeURIComponent(claim.workflow.workflow_id)}/tools/${encodeURIComponent(declared.name)}`,
        {
          method: 'POST',
          body: JSON.stringify({
            arguments: argumentsPayload,
            worker_id: workerId
          })
        }
      );
      const result = queued.action_id
        ? await waitForTool(claim.workflow.workflow_id, queued.action_id, claim.action_id)
        : queued;
      const visibleResult = result.data === undefined
        ? result.workflow
        : { workflow: result.workflow, data: result.data };
      return {
        content: [{ type: 'text' as const, text: JSON.stringify(visibleResult) }],
        details: visibleResult
      };
    }
  }));
}

function systemPrompt(claim: HarnessClaim): string {
  return [
    '你是财务平台后台运行的 Pi Harness。你负责把当前核销日从准备材料执行到最终完成。',
    '下面的 SKILL.md 来自任务创建时固定的 Skill 快照，必须完整遵守。',
    '任务完整上下文也来自平台当前任务记录。你可以读取其中的输入材料元数据、业务上下文、过程消息、动作输入输出、产物和批次状态。',
    '完成取数预览后、确认取数包前，调用 inspect_fetched_data，并根据 total、offset、limit 翻页读完当前核销日的全部记录。',
    '需要核对任务中的 JSON、CSV、Markdown、YAML 或文本产物时，调用 read_task_file；使用返回的 next_offset 继续读取，直到达到 total_bytes。',
    '只能调用本会话提供的受控工具。每次读取工具结果后再决定下一步。',
    '不得要求用户在执行过程中补充确认。发现数据或工具错误时立即停止。',
    '写入失败后不得重试。多日批次由平台按日期从早到晚逐日创建本会话。',
    '调用 apply_reconciliation 时，必须逐字复制最近工具结果中 context.pi_harness_write_guard 的四个字段。',
    '只有 workflow.state 已变为 succeeded 或 cancelled 才能结束；多日最后一天还要调用 finalize_batch。',
    '',
    `固定 Skill：${claim.skill.id} ${claim.skill.version}`,
    `固定 Skill 哈希：${claim.skill.hash}`,
    '',
    '任务完整上下文：',
    JSON.stringify(claim.workflow),
    '',
    claim.skill.instructions
  ].join('\n');
}

async function finish(claim: HarnessClaim, outcome: 'succeeded' | 'failed', message = '') {
  await apiRequest(`/api/internal/pi-harness/actions/${encodeURIComponent(claim.action_id)}/finish`, {
    method: 'POST',
    body: JSON.stringify({ worker_id: workerId, outcome, message })
  });
}

async function executeClaim(claim: HarnessClaim): Promise<void> {
  const modelHandle = createPlatformModel({
    modelId: claim.model,
    gatewayUrl: `${apiBase}/api/internal/pi-harness/model`,
    accessToken: token,
    gatewayFields: {
      workflow_id: claim.workflow.workflow_id,
      harness_action_id: claim.action_id,
      worker_id: workerId
    }
  });
  const runtime = new PiAgentRuntime({ streamFn: modelHandle.streamSimple, maxSessions: 1 });
  const heartbeatTimer = setInterval(() => {
    void heartbeat(claim.action_id).catch(() => {
      stopping = true;
    });
  }, 10_000);
  let runtimeError = '';
  try {
    const events = runtime.startTurn({
      sessionId: claim.action_id,
      ownerId: claim.workflow.workflow_id,
      model: modelHandle.model,
      message: `执行 ${claim.workflow.reconciliation_date} 的应收核销，完成全部 Skill 步骤。`,
      systemPrompt: systemPrompt(claim),
      tools: createHarnessTools(claim)
    });
    for await (const event of events) {
      if (event.type === 'error') runtimeError = event.message;
    }
    const current = await apiRequest<ToolResponse>(
      `/api/internal/pi-harness/workflows/${encodeURIComponent(claim.workflow.workflow_id)}/actions/${encodeURIComponent(claim.action_id)}?worker_id=${encodeURIComponent(workerId)}`
    );
    if (!runtimeError && ['succeeded', 'cancelled'].includes(current.workflow.state)) {
      await finish(claim, 'succeeded');
    } else {
      await finish(claim, 'failed', runtimeError || 'Pi Harness 未完成 Skill 的全部步骤。');
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Pi Harness 执行失败。';
    await finish(claim, 'failed', message).catch(() => undefined);
  } finally {
    clearInterval(heartbeatTimer);
  }
}

async function main(): Promise<void> {
  process.on('SIGINT', () => {
    stopping = true;
  });
  process.on('SIGTERM', () => {
    stopping = true;
  });
  while (!stopping) {
    const claim = await apiRequest<HarnessClaim | null>('/api/internal/pi-harness/claim', {
      method: 'POST',
      body: JSON.stringify({ worker_id: workerId })
    });
    if (claim) await executeClaim(claim);
    else await delay(pollMilliseconds);
  }
}

void main().catch(() => {
  process.exitCode = 1;
});
