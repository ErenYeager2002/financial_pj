import {
  Agent,
  type AgentMessage,
  type AgentTool,
  type StreamFn
} from '@earendil-works/pi-agent-core';
import type {
  AgentEvent,
  AgentRuntime,
  AgentRuntimeRequest,
  AgentSessionState,
  RuntimeModel
} from './contracts.js';
import { AsyncQueue } from './async-queue.js';

interface RuntimeSession {
  ownerId: string;
  agent: Agent;
  allowedTools: Set<string>;
}

interface ConfirmationDetails {
  awaitConfirmation?: boolean;
  confirmationMessage?: string;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Agent 运行失败。';
}

function confirmationDetails(value: unknown): ConfirmationDetails {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const details = value as Record<string, unknown>;
  return {
    awaitConfirmation: details.awaitConfirmation === true,
    confirmationMessage:
      typeof details.confirmationMessage === 'string' ? details.confirmationMessage : undefined
  };
}

function toolDetails(value: unknown): unknown {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
  const result = value as Record<string, unknown>;
  return 'details' in result ? result.details : value;
}

function mapEvent(event: unknown): AgentEvent[] {
  if (!event || typeof event !== 'object') return [];
  const value = event as Record<string, unknown>;
  if (value.type === 'message_update') {
    const assistant = value.assistantMessageEvent;
    if (!assistant || typeof assistant !== 'object') return [];
    const update = assistant as Record<string, unknown>;
    if (update.type === 'text_delta' && typeof update.delta === 'string') {
      return [{ type: 'text_delta', delta: update.delta }];
    }
    return [];
  }
  if (value.type === 'tool_execution_start') {
    const toolCallId = typeof value.toolCallId === 'string' ? value.toolCallId : '';
    const toolName = typeof value.toolName === 'string' ? value.toolName : '';
    if (!toolCallId || !toolName) return [];
    return [{ type: 'tool_start', toolCallId, toolName }];
  }
  if (value.type === 'tool_execution_end') {
    const toolCallId = typeof value.toolCallId === 'string' ? value.toolCallId : '';
    const toolName = typeof value.toolName === 'string' ? value.toolName : '';
    if (!toolCallId || !toolName) return [];
    const details = toolDetails(value.result);
    const result = confirmationDetails(details);
    const events: AgentEvent[] = [{
      type: 'tool_result',
      toolCallId,
      toolName,
      isError: value.isError === true,
      awaitConfirmation: result.awaitConfirmation === true,
      details
    }];
    if (result.awaitConfirmation) {
      events.push({
        type: 'await_confirmation',
        toolCallId,
        toolName,
        message: result.confirmationMessage ?? '该操作需要用户确认后才能继续。'
      });
    }
    return events;
  }
  return [];
}

export interface PiAgentRuntimeOptions {
  streamFn: StreamFn;
  maxSessions?: number;
}

export class PiAgentRuntime implements AgentRuntime {
  private readonly sessions = new Map<string, RuntimeSession>();
  private readonly streamFn: StreamFn;
  private readonly maxSessions: number;

  constructor(options: PiAgentRuntimeOptions) {
    this.streamFn = options.streamFn;
    this.maxSessions = options.maxSessions ?? 100;
  }

  startTurn(request: AgentRuntimeRequest): AsyncIterable<AgentEvent> {
    const queue = new AsyncQueue<AgentEvent>();
    void this.runTurn(request, queue);
    return queue;
  }

  abort(sessionId: string, ownerId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session || session.ownerId !== ownerId) return;
    session.agent.abort();
  }

  getSessionState(sessionId: string, ownerId: string): AgentSessionState | null {
    const session = this.sessions.get(sessionId);
    if (!session || session.ownerId !== ownerId) return null;
    return {
      sessionId,
      ownerId,
      isStreaming: session.agent.state.isStreaming,
      messages: session.agent.state.messages
    };
  }

  private async runTurn(request: AgentRuntimeRequest, queue: AsyncQueue<AgentEvent>): Promise<void> {
    try {
      const session = this.getOrCreateSession(request);
      const unsubscribe = session.agent.subscribe((event) => {
        for (const mapped of mapEvent(event)) queue.push(mapped);
      });
      try {
        await session.agent.prompt(request.message);
        queue.push({ type: 'done', messageCount: session.agent.state.messages.length });
      } finally {
        unsubscribe();
      }
      queue.close();
    } catch (error) {
      queue.push({ type: 'error', code: 'agent_runtime_error', message: errorMessage(error) });
      queue.close();
    }
  }

  private getOrCreateSession(request: AgentRuntimeRequest): RuntimeSession {
    const existing = this.sessions.get(request.sessionId);
    if (existing) {
      if (existing.ownerId !== request.ownerId) {
        throw new Error('Agent 会话不属于当前用户。');
      }
      existing.agent.state.systemPrompt = request.systemPrompt;
      existing.agent.state.model = request.model;
      existing.agent.state.tools = [...request.tools];
      existing.allowedTools.clear();
      for (const tool of request.tools) existing.allowedTools.add(tool.name);
      return existing;
    }
    if (this.sessions.size >= this.maxSessions) {
      const oldest = this.sessions.keys().next().value;
      if (typeof oldest === 'string') this.sessions.delete(oldest);
    }
    const allowedTools = new Set(request.tools.map((tool) => tool.name));
    const agent = new Agent({
      initialState: {
        systemPrompt: request.systemPrompt,
        model: request.model,
        messages: [...(request.initialMessages ?? [])],
        tools: [...request.tools]
      },
      streamFn: this.streamFn,
      toolExecution: 'sequential',
      beforeToolCall: async ({ toolCall }) => {
        if (!allowedTools.has(toolCall.name)) {
          return {
            block: true,
            reason: '当前 Agent 会话未授权该工具。',
            terminate: true
          };
        }
        return undefined;
      }
    });
    const session = { ownerId: request.ownerId, agent, allowedTools };
    this.sessions.set(request.sessionId, session);
    return session;
  }
}

export type { AgentTool, AgentMessage, RuntimeModel };
