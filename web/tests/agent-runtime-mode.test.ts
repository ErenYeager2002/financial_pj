import assert from 'node:assert/strict';
import test from 'node:test';
import {
  legacyFallbackEnabled,
  resolveAgentRuntime,
  runtimeSelectorId,
  withLegacyFallback
} from '../src/features/ai-chat/runtime-mode.ts';
import { safeCatalog } from '../src/features/ai-chat/safe-catalog.ts';

async function* errorPiEvents() {
  yield { type: 'error' as const, code: 'agent_runtime_error', message: 'upstream' };
}

async function* legacyDoneEvents() {
  yield { type: 'done' as const, messageCount: 0 };
}

async function* emptyPiEvents() {
  yield { type: 'done' as const, messageCount: 0 };
}

async function* toolThenErrorEvents() {
  yield { type: 'tool_start' as const, toolCallId: 'call-1', toolName: 'business_tool' };
  yield { type: 'error' as const, code: 'agent_runtime_error', message: 'upstream' };
}

function makeSyntheticSkill(overrides: Record<string, unknown>) {
  return {
    id: 'synthetic-readonly',
    name: '合成只读 Skill',
    version: '1.0.0',
    status: 'published',
    description: '只读测试能力',
    categories: [],
    tags: [],
    estimated_minutes: 1,
    output_summary: '测试结果',
    action_label: '开始',
    popular: false,
    execution_mode: 'standard',
    risk: {
      level: 'read_only',
      requires_confirmation: false,
      requires_approval: false,
      modifies_uploaded_files: false
    },
    file_inputs: [],
    input_schema: {},
    progress_stages: [],
    result_presentation: { metrics: [] },
    ...overrides
  } as never;
}

test('explicit legacy mode only enables Pi for the configured test users', () => {
  const environment = {
    AGENT_RUNTIME: 'legacy',
    AGENT_RUNTIME_PI_USERS: 'clerk_test, clerk_admin'
  };

  assert.equal(resolveAgentRuntime('ordinary-user', environment), 'legacy');
  assert.equal(resolveAgentRuntime('clerk_test', environment), 'pi');
  assert.equal(resolveAgentRuntime('clerk_admin', environment), 'pi');
});

test('runtime gray switch prefers Clerk identity and falls back to platform identity', () => {
  assert.equal(runtimeSelectorId('user_clerk_123', 'platform-123'), 'user_clerk_123');
  assert.equal(runtimeSelectorId('  ', 'platform-123'), 'platform-123');
  assert.equal(runtimeSelectorId(null, 'platform-123'), 'platform-123');
});

test('explicit Pi mode enables the runtime for all authenticated users', () => {
  assert.equal(resolveAgentRuntime('ordinary-user', { AGENT_RUNTIME: 'pi' }), 'pi');
});

test('unknown configuration remains on the legacy runtime while empty uses Pi', () => {
  assert.equal(resolveAgentRuntime('ordinary-user', { AGENT_RUNTIME: 'unknown' }), 'legacy');
  assert.equal(resolveAgentRuntime('ordinary-user', {}), 'pi');
});

test('legacy fallback is opt-in so ordinary chat failures do not become task drafts', () => {
  assert.equal(legacyFallbackEnabled({}), false);
  assert.equal(legacyFallbackEnabled({ AGENT_RUNTIME_FALLBACK: 'legacy' }), true);
  assert.equal(legacyFallbackEnabled({ AGENT_RUNTIME_FALLBACK: 'off' }), false);
});

test('Pi errors remain visible by default instead of replaying the task-only legacy flow', async () => {
  let fallbackCalled = false;
  async function* legacyEvents() {
    fallbackCalled = true;
    yield { type: 'done' as const, messageCount: 0 };
  }

  const events = [];
  for await (const event of withLegacyFallback(errorPiEvents(), legacyEvents, {})) {
    events.push(event);
  }

  assert.equal(fallbackCalled, false);
  assert.deepEqual(events, [{ type: 'error', code: 'agent_runtime_error', message: 'upstream' }]);
});

test('Pi errors before any work can use an explicitly enabled legacy fallback', async () => {
  const events = [];
  for await (const event of withLegacyFallback(errorPiEvents(), legacyDoneEvents, {
    AGENT_RUNTIME_FALLBACK: 'legacy'
  })) {
    events.push(event);
  }
  assert.deepEqual(events, [{ type: 'done', messageCount: 0 }]);
});

test('Pi completes without text or tools by falling back to the legacy draft flow', async () => {
  let fallbackCalled = false;
  async function* legacyEvents() {
    fallbackCalled = true;
    yield { type: 'tool_start' as const, toolCallId: 'legacy', toolName: 'prepare_task_draft' };
    yield { type: 'done' as const, messageCount: 0 };
  }

  const events = [];
  for await (const event of withLegacyFallback(emptyPiEvents(), legacyEvents, {
    AGENT_RUNTIME_FALLBACK: 'legacy'
  })) {
    events.push(event);
  }

  assert.equal(fallbackCalled, true);
  assert.equal(events[0]?.type, 'tool_start');
  assert.equal(events.at(-1)?.type, 'done');
});

test('Pi empty responses surface a chat error when legacy fallback is disabled', async () => {
  const events = [];
  for await (const event of withLegacyFallback(emptyPiEvents(), legacyDoneEvents, {})) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      type: 'error',
      code: 'assistant_no_response',
      message: 'AI 助手没有返回内容，请重试。'
    }
  ]);
});

test('Pi errors after a tool starts never replay the legacy flow', async () => {
  let fallbackCalled = false;
  async function* legacyEvents() {
    fallbackCalled = true;
    yield { type: 'done' as const, messageCount: 0 };
  }

  const events = [];
  for await (const event of withLegacyFallback(toolThenErrorEvents(), legacyEvents, {})) {
    events.push(event);
  }
  assert.equal(fallbackCalled, false);
  assert.equal(events.at(-1)?.type, 'error');
});

test('ordinary Pi Skill catalog excludes workflow and write Skills', () => {
  const catalog = safeCatalog([
    makeSyntheticSkill({}),
    makeSyntheticSkill({
      id: 'ar-hexiao-daily',
      execution_mode: 'guided_workflow',
      risk: { level: 'write' }
    }),
    makeSyntheticSkill({ id: 'write-skill', risk: { level: 'write' } }),
    makeSyntheticSkill({
      id: 'file-mutating-skill',
      risk: { level: 'read_only', modifies_uploaded_files: true }
    })
  ]);

  assert.deepEqual(
    catalog.map((item) => item.id),
    ['synthetic-readonly']
  );
});
