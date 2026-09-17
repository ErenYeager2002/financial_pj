import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import * as skillScope from '../src/features/ai-chat/skill-chat-scope.ts';
import * as turnState from '../src/features/ai-chat/turn-state.ts';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(r => { resolve = r; });
  return { promise, resolve };
}

function fixture() {
  const gate = deferred();
  const saved = deferred();
  let aborted = false;
  let owner = 'owner';
  const messages: string[] = [];
  const metadata: unknown[] = [];
  class ApiError extends Error { status: number; constructor(status: number, message: string) { super(message); this.status = status; } }
  const source = readFileSync(new URL('../src/app/api/platform/assistant/turn/route.ts', import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports: Record<string, any> = {};
  const dependencies: Record<string, unknown> = {
    '@/features/ai-chat/turn-state': turnState,
    '@/features/ai-chat/skill-chat-scope': skillScope,
    '@/features/ai-chat/agent-server': { createAssistantTurn: async () => ({
      abort: () => { aborted = true; },
      events: (async function* () {
        yield { type: 'text_delta', delta: '第一段' };
        await gate.promise;
        if (aborted) throw new Error('aborted by navigation');
        yield { type: 'text_delta', delta: '完整回复' };
        yield { type: 'tool_result', details: { draft: { id: 'persisted-draft' } } };
        yield { type: 'done' };
      })()
    }) },
    '@/features/ai-chat/api/server': { appendAssistantMessage: async (_s: string, role: string, content: string, data: unknown) => {
      if (role === 'assistant') { messages.push(content); metadata.push(data); saved.resolve(); }
    } },
    '@/features/platform-api/errors': { PlatformApiError: ApiError },
    '@/features/platform-api/route-handler': { platformRouteError: (error: ApiError) => new Response('', { status: error.status ?? 500 }) },
    '@/features/platform-api/server-client': { platformServerRequest: async () => ({ user_id: owner }) }
  };
  new Function('require', 'exports', compiled)((name: string) => {
    if (!(name in dependencies)) throw new Error('Unexpected dependency: ' + name);
    return dependencies[name];
  }, exports);
  return { exports, gate, saved, messages, metadata, isAborted: () => aborted, setOwner: (value: string) => { owner = value; } };
}

test('leaving the page keeps generation alive and persists the complete answer', async () => {
  const f = fixture();
  const controller = new AbortController();
  const response = await f.exports.POST(new Request('http://test/turn', {
    method: 'POST', signal: controller.signal,
    body: JSON.stringify({ session_id: 'session', message: '测试', file_ids: [] })
  }));
  const reader = response.body!.getReader();
  await reader.read();
  controller.abort();
  // The request abort represents navigation; do not cancel the test reader,
  // so old code can surface its error frame without unhandled enqueue errors.
  f.gate.resolve();
  await f.saved.promise;
  await reader.cancel();
  assert.equal(f.isAborted(), false, 'navigation must not cancel the model');
  assert.deepEqual(f.messages, ['第一段完整回复']);
  assert.deepEqual(f.metadata, [{ draft_id: 'persisted-draft' }]);
});


test('reader cancellation cannot turn a successful answer into a saved processing error', async () => {
  const f = fixture();
  const response = await f.exports.POST(new Request('http://test/turn', { method: 'POST', body: JSON.stringify({ session_id: 'cancel-reader', message: 'test' }) }));
  const reader = response.body!.getReader();
  await reader.read();
  await reader.cancel();
  f.gate.resolve();
  await f.saved.promise;
  assert.equal(f.isAborted(), false);
  assert.deepEqual(f.messages, ['第一段完整回复']);
  assert.deepEqual(f.metadata, [{ draft_id: 'persisted-draft' }]);
});

test('returning user sees active state; only explicit owner stop cancels generation', async () => {
  const f = fixture();
  const response = await f.exports.POST(new Request('http://test/turn', { method: 'POST', body: JSON.stringify({ session_id: 'explicit-stop', message: 'test' }) }));
  const reader = response.body!.getReader(); await reader.read();
  const status = () => f.exports.GET(new Request('http://test/turn?session_id=explicit-stop'));
  assert.equal((await (await status()).json()).active, true);
  const duplicate = await f.exports.POST(new Request('http://test/turn', { method: 'POST', body: JSON.stringify({ session_id: 'explicit-stop', message: 'duplicate' }) }));
  assert.equal(duplicate.status, 409);
  f.setOwner('other');
  assert.equal((await (await status()).json()).active, false);
  await f.exports.DELETE(new Request('http://test/turn', { method: 'DELETE', body: JSON.stringify({ session_id: 'explicit-stop' }) }));
  assert.equal(f.isAborted(), false);
  f.setOwner('owner');
  await f.exports.DELETE(new Request('http://test/turn', { method: 'DELETE', body: JSON.stringify({ session_id: 'explicit-stop' }) }));
  assert.equal(f.isAborted(), true);
  f.gate.resolve(); await f.saved.promise;
  while (!(await reader.read()).done) {}
  assert.equal((await (await status()).json()).active, false);
});
