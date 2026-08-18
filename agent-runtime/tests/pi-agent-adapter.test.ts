import assert from 'node:assert/strict';
import test from 'node:test';
import { fauxAssistantMessage, fauxProvider, fauxText, fauxToolCall, createModels } from '@earendil-works/pi-ai';
import { Type } from 'typebox';
import { PiAgentRuntime } from '../dist/pi-agent-adapter.js';

function createEchoTool(onExecute: () => void) {
  return {
    name: 'echo',
    label: '回显',
    description: '返回传入的文本。',
    parameters: Type.Object({ text: Type.String() }),
    execute: async (_toolCallId: string, params: { text: string }) => {
      onExecute();
      return {
        content: [{ type: 'text' as const, text: `工具收到：${params.text}` }],
        details: { accepted: true }
      };
    }
  };
}

async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const result: T[] = [];
  for await (const item of items) result.push(item);
  return result;
}

test('Pi runtime streams text and executes only the supplied business tool', async () => {
  const faux = fauxProvider({ provider: `test-runtime-${Date.now()}`, tokensPerSecond: 0 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall('echo', { text: 'hello' }, { id: 'call-1' }), { stopReason: 'toolUse' }),
    fauxAssistantMessage(fauxText('已完成。'), { stopReason: 'stop' })
  ]);

  let executionCount = 0;
  const tool = createEchoTool(() => executionCount++);
  const runtime = new PiAgentRuntime({ streamFn: models.streamSimple.bind(models) });
  const events = await collect(runtime.startTurn({
    sessionId: 'session-1',
    ownerId: 'user-1',
    model: faux.getModel() as never,
    message: '执行回显',
    systemPrompt: '只使用传入的工具。',
    tools: [tool]
  }));

  assert.equal(executionCount, 1);
  assert.deepEqual(events.filter((event) => event.type), [
    { type: 'tool_start', toolCallId: 'call-1', toolName: 'echo' },
    {
      type: 'tool_result',
      toolCallId: 'call-1',
      toolName: 'echo',
      isError: false,
      awaitConfirmation: false,
      details: { accepted: true }
    },
    { type: 'text_delta', delta: '已完成。' },
    { type: 'done', messageCount: 4 }
  ]);

  const state = runtime.getSessionState('session-1', 'user-1');
  assert.ok(state);
  assert.equal(state.isStreaming, false);
  assert.equal(state.messages.length, 4);
  assert.equal(runtime.getSessionState('session-1', 'other-user'), null);
});

test('Pi runtime blocks a tool that was not supplied by the platform', async () => {
  const faux = fauxProvider({ provider: `test-block-${Date.now()}`, tokensPerSecond: 0 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall('not-authorized', {}, { id: 'call-blocked' }), { stopReason: 'toolUse' })
  ]);

  let executionCount = 0;
  const runtime = new PiAgentRuntime({ streamFn: models.streamSimple.bind(models) });
  const events = await collect(runtime.startTurn({
    sessionId: 'session-blocked',
    ownerId: 'user-1',
    model: faux.getModel() as never,
    message: '调用未授权工具',
    systemPrompt: '禁止未授权工具。',
    tools: [createEchoTool(() => executionCount++)]
  }));

  assert.equal(executionCount, 0);
  assert.ok(events.some((event) => event.type === 'tool_result' && event.isError));
  assert.ok(events.some((event) => event.type === 'done' || event.type === 'error'));
});

test('Pi runtime requires the same owner when reusing a session', async () => {
  const faux = fauxProvider({ provider: `test-owner-${Date.now()}`, tokensPerSecond: 0 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([fauxAssistantMessage(fauxText('ok'), { stopReason: 'stop' })]);

  const runtime = new PiAgentRuntime({ streamFn: models.streamSimple.bind(models) });
  await collect(runtime.startTurn({
    sessionId: 'session-owner',
    ownerId: 'user-1',
    model: faux.getModel() as never,
    message: '你好',
    systemPrompt: '测试',
    tools: []
  }));

  const events = await collect(runtime.startTurn({
    sessionId: 'session-owner',
    ownerId: 'user-2',
    model: faux.getModel() as never,
    message: '越权',
    systemPrompt: '测试',
    tools: []
  }));
  assert.equal(events.length, 1);
  assert.equal(events[0]?.type, 'error');
  assert.equal(runtime.getSessionState('session-owner', 'user-1')?.messages.length, 2);
});

test('Pi runtime can interrupt a turn and resume the same owned session', async () => {
  const faux = fauxProvider({
    provider: `test-abort-${Date.now()}`,
    tokensPerSecond: 1000,
    tokenSize: { min: 1, max: 1 }
  });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    fauxAssistantMessage(fauxText('x'.repeat(500)), { stopReason: 'stop' }),
    fauxAssistantMessage(fauxText('恢复完成。'), { stopReason: 'stop' })
  ]);

  const runtime = new PiAgentRuntime({ streamFn: models.streamSimple.bind(models) });
  const firstTurn = runtime.startTurn({
    sessionId: 'session-resume',
    ownerId: 'user-1',
    model: faux.getModel() as never,
    message: '开始长响应',
    systemPrompt: '允许中断并恢复。',
    tools: []
  });
  const iterator = firstTurn[Symbol.asyncIterator]();
  const firstEvent = await iterator.next();
  assert.equal(firstEvent.done, false);
  runtime.abort('session-resume', 'user-1');

  while (true) {
    const next = await iterator.next();
    if (next.done) break;
  }
  assert.equal(runtime.getSessionState('session-resume', 'user-1')?.isStreaming, false);

  const resumedEvents = await collect(
    runtime.startTurn({
      sessionId: 'session-resume',
      ownerId: 'user-1',
      model: faux.getModel() as never,
      message: '继续',
      systemPrompt: '允许中断并恢复。',
      tools: []
    })
  );
  const resumedText = resumedEvents
    .filter((event) => event.type === 'text_delta')
    .map((event) => event.delta)
    .join('');
  assert.equal(resumedText, '恢复完成。');
  assert.ok(resumedEvents.some((event) => event.type === 'done'));
});

test('Pi runtime exposes a confirmation event without executing a second business action', async () => {
  const faux = fauxProvider({ provider: `test-confirm-${Date.now()}`, tokensPerSecond: 0 });
  const models = createModels();
  models.setProvider(faux.provider);
  faux.setResponses([
    fauxAssistantMessage(fauxToolCall('confirmable', {}, { id: 'call-confirm' }), {
      stopReason: 'toolUse'
    }),
    fauxAssistantMessage(fauxText('等待确认。'), { stopReason: 'stop' })
  ]);

  const confirmable = {
    name: 'confirmable',
    label: '需要确认的操作',
    description: '只返回待确认状态。',
    parameters: Type.Object({}),
    execute: async () => ({
      content: [{ type: 'text' as const, text: '等待确认' }],
      details: {
        awaitConfirmation: true,
        confirmationMessage: '请确认后继续。'
      }
    })
  };
  const runtime = new PiAgentRuntime({ streamFn: models.streamSimple.bind(models) });
  const events = await collect(runtime.startTurn({
    sessionId: 'session-confirm',
    ownerId: 'user-1',
    model: faux.getModel() as never,
    message: '执行待确认操作',
    systemPrompt: '测试确认门。',
    tools: [confirmable]
  }));

  assert.ok(events.some((event) => event.type === 'await_confirmation'));
  assert.deepEqual(
    events.find((event) => event.type === 'await_confirmation'),
    {
      type: 'await_confirmation',
      toolCallId: 'call-confirm',
      toolName: 'confirmable',
      message: '请确认后继续。'
    }
  );
});
