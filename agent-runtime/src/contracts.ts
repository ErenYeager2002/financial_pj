import type { AgentMessage, AgentTool } from '@earendil-works/pi-agent-core';
import type { Api, Model } from '@earendil-works/pi-ai';

export type RuntimeModel = Model<Api>;

export interface AgentRuntimeRequest {
  sessionId: string;
  ownerId: string;
  model: RuntimeModel;
  message: string;
  systemPrompt: string;
  initialMessages?: readonly AgentMessage[];
  tools: readonly AgentTool[];
}

export interface AgentSessionState {
  sessionId: string;
  ownerId: string;
  isStreaming: boolean;
  messages: readonly AgentMessage[];
}

export interface AgentTextDeltaEvent {
  type: 'text_delta';
  delta: string;
}

export interface AgentToolStartEvent {
  type: 'tool_start';
  toolCallId: string;
  toolName: string;
}

export interface AgentToolResultEvent {
  type: 'tool_result';
  toolCallId: string;
  toolName: string;
  isError: boolean;
  awaitConfirmation: boolean;
  details?: unknown;
}

export interface AgentAwaitConfirmationEvent {
  type: 'await_confirmation';
  toolCallId: string;
  toolName: string;
  message: string;
}

export interface AgentErrorEvent {
  type: 'error';
  message: string;
  code: string;
}

export interface AgentDoneEvent {
  type: 'done';
  messageCount: number;
}

export type AgentEvent =
  | AgentTextDeltaEvent
  | AgentToolStartEvent
  | AgentToolResultEvent
  | AgentAwaitConfirmationEvent
  | AgentErrorEvent
  | AgentDoneEvent;

export interface AgentRuntime {
  startTurn(request: AgentRuntimeRequest): AsyncIterable<AgentEvent>;
  abort(sessionId: string, ownerId: string): void;
  getSessionState(sessionId: string, ownerId: string): AgentSessionState | null;
}
