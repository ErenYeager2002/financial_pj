export interface AgentWireRecord {
  [key: string]: unknown;
}

export type AgentWireEvent =
  | { type: 'text_delta'; delta: string }
  | { type: 'tool_start'; toolCallId: string; toolName: string }
  | {
      type: 'tool_result';
      toolCallId: string;
      toolName: string;
      isError: boolean;
      awaitConfirmation: boolean;
      details?: unknown;
    }
  | { type: 'await_confirmation'; toolCallId: string; toolName: string; message: string }
  | { type: 'error'; message: string; code: string }
  | { type: 'done'; messageCount: number };

function recordValue(value: unknown): AgentWireRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as AgentWireRecord)
    : null;
}

function stringField(record: AgentWireRecord, key: string): string {
  const value = record[key];
  if (typeof value !== 'string') throw new Error(`AI 事件缺少字符串字段：${key}。`);
  return value;
}

function booleanField(record: AgentWireRecord, key: string): boolean {
  const value = record[key];
  if (typeof value !== 'boolean') throw new Error(`AI 事件缺少布尔字段：${key}。`);
  return value;
}

function integerField(record: AgentWireRecord, key: string): number {
  const value = record[key];
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new Error(`AI 事件缺少非负整数：${key}。`);
  }
  return value;
}

export function parseAgentWireEvent(value: unknown): AgentWireEvent {
  const record = recordValue(value);
  if (!record || typeof record.type !== 'string') {
    throw new Error('AI 助手返回了无法识别的事件。');
  }

  switch (record.type) {
    case 'text_delta':
      return { type: 'text_delta', delta: stringField(record, 'delta') };
    case 'tool_start':
      return {
        type: 'tool_start',
        toolCallId: stringField(record, 'toolCallId'),
        toolName: stringField(record, 'toolName')
      };
    case 'tool_result':
      return {
        type: 'tool_result',
        toolCallId: stringField(record, 'toolCallId'),
        toolName: stringField(record, 'toolName'),
        isError: booleanField(record, 'isError'),
        awaitConfirmation: booleanField(record, 'awaitConfirmation'),
        details: record.details
      };
    case 'await_confirmation':
      return {
        type: 'await_confirmation',
        toolCallId: stringField(record, 'toolCallId'),
        toolName: stringField(record, 'toolName'),
        message: stringField(record, 'message')
      };
    case 'error':
      return {
        type: 'error',
        message: stringField(record, 'message'),
        code: stringField(record, 'code')
      };
    case 'done':
      return { type: 'done', messageCount: integerField(record, 'messageCount') };
    default:
      throw new Error(`AI 助手返回了不支持的事件类型：${record.type}。`);
  }
}
