import assert from 'node:assert/strict';
import test from 'node:test';
import {piRequest} from '../src/features/pi-runtime/pi-client.ts';

test('a cancelled observation cannot dispatch another initialization command', async context => {
  const controller = new AbortController();
  controller.abort();
  let calls = 0;
  context.mock.method(globalThis, 'fetch', async () => {calls++; return new Response('{}');});
  await assert.rejects(piRequest('/sessions/example/operate', {operation: 'send', payload: {command: {type: 'get_state'}}}, controller.signal), {name: 'AbortError'});
  assert.equal(calls, 0);
});

test('passes the observation signal without sending a stop or abort command', async context => {
  const controller = new AbortController();
  const sent: unknown[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/platform/pi-runtime/sessions/example/operate');
    assert.equal(options.signal, controller.signal);
    sent.push(JSON.parse(String(options.body)));
    return new Response('{"accepted":true}');
  });
  const body = {operation: 'send', payload: {command: {type: 'get_messages', id: 'observation'}}};
  assert.deepEqual(await piRequest('/sessions/example/operate', body, controller.signal), {accepted: true});
  controller.abort();
  assert.deepEqual(sent, [body]);
});

test('ignores a late transport response even when transport did not honor abort', async context => {
  const controller = new AbortController();
  context.mock.method(globalThis, 'fetch', async () => {
    controller.abort();
    return new Response('{"messages":["old-account"]}');
  });
  await assert.rejects(piRequest('/sessions/old/history', undefined, controller.signal), {name: 'AbortError'});
});

test('cancellation during body decoding stops initialization before the next read', async context => {
  const controller = new AbortController();
  let calls = 0;
  context.mock.method(globalThis, 'fetch', async () => {
    calls++;
    const response = new Response('{}');
    context.mock.method(response, 'json', async () => {controller.abort(); return {};});
    return response;
  });
  async function hydrate() {
    await piRequest('/sessions/example/operate', {operation: 'send', payload: {command: {type: 'get_messages'}}}, controller.signal);
    await piRequest('/sessions/example/operate', {operation: 'send', payload: {command: {type: 'get_state'}}}, controller.signal);
  }
  await assert.rejects(hydrate(), {name: 'AbortError'});
  assert.equal(calls, 1);
});

test('an uncancelled server error retains its message', async context => {
  context.mock.method(globalThis, 'fetch', async () => new Response('{"detail":"session unavailable"}', {status: 403}));
  await assert.rejects(piRequest('/sessions/example/history', undefined, new AbortController().signal), /session unavailable/);
});

test('a submitted mutation without an observation signal still returns its receipt', async context => {
  context.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit) => {
    assert.equal(options.signal, undefined);
    return new Response('{"delivery_state":"pi_accepted"}');
  });
  assert.deepEqual(await piRequest('/sessions/example/operate', {operation: 'send', payload: {command: {type: 'prompt', message: 'synthetic'}}}), {delivery_state: 'pi_accepted'});
});
