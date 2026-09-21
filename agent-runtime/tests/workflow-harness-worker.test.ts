import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

// Actual compiled Worker + Pi runtime, synthetic loopback API/model only.
test('harness carries one claim attempt through model, tool, heartbeat, read and finish', { timeout: 20000 }, async () => {
  const actionId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const workflowId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const observed: { path: string; body: Record<string, unknown>; query: URLSearchParams }[] = [];
  let claimed = false;
  let modelCalls = 0;
  let finishResolve: () => void = () => {};
  const finished = new Promise<void>((resolve) => { finishResolve = resolve; });
  const workflow = { workflow_id: workflowId, state: 'running', stage: 'preparing',
    reconciliation_date: '2026-09-21', context: {}, actions: [], messages: [], artifacts: [],
    files: {}, material: {}, model: {}, skill: {}, batch: null };
  const server = http.createServer(async (request, response) => {
    let raw = '';
    for await (const part of request) raw += part;
    const body = raw ? JSON.parse(raw) : {};
    const url = new URL(request.url ?? '/', 'http://localhost');
    observed.push({ path: url.pathname, body, query: url.searchParams });
    const json = (value: unknown) => {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify(value));
    };
    if (url.pathname.endsWith('/claim')) {
      if (claimed) { json(null); return; }
      claimed = true;
      json({ action_id: actionId, attempt: 7, protocol_version: 'pi-harness-attempt-v1',
        workflow, model: 'synthetic-workflow-model',
        skill: { id: 'synthetic', version: '1', hash: 'a'.repeat(64), instructions: 'Call prepare_workspace then finish.',
          tools: [{ name: 'prepare_workspace', description: 'Synthetic tool.', required_arguments: [] }] } });
    } else if (url.pathname.endsWith('/chat/completions')) {
      modelCalls++;
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      const delta = modelCalls === 1
        ? { role: 'assistant', tool_calls: [{ index: 0, id: 'call_synthetic', type: 'function',
            function: { name: 'prepare_workspace', arguments: '{}' } }] }
        : { role: 'assistant', content: 'Done.' };
      const chunk = { id: 'synthetic-response', object: 'chat.completion.chunk', created: 1,
        model: 'synthetic-workflow-model', choices: [{ index: 0, delta, finish_reason: null }] };
      response.write('data: ' + JSON.stringify(chunk) + '\n\n');
      response.write('data: ' + JSON.stringify({ ...chunk, choices: [{ index: 0, delta: {},
        finish_reason: modelCalls === 1 ? 'tool_calls' : 'stop' }] }) + '\n\n');
      response.end('data: [DONE]\n\n');
    } else if (url.pathname.endsWith('/tools/prepare_workspace')) {
      json({ action_id: 'tool-action', state: 'queued', workflow });
    } else if (url.pathname.endsWith('/heartbeat')) {
      json({ state: 'running' });
    } else if (url.pathname.includes('/actions/') && request.method === 'GET') {
      json({ action_id: actionId, state: 'succeeded', workflow: { ...workflow, state: 'succeeded' } });
    } else if (url.pathname.endsWith('/finish')) {
      json({ state: 'succeeded' });
      finishResolve();
    } else {
      response.writeHead(404); response.end();
    }
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const child = spawn(process.execPath, ['dist/workflow-harness-worker.js'], {
    env: { ...process.env, FINANCIAL_PLATFORM_API_URL: `http://127.0.0.1:${address.port}`,
      FINANCIAL_PI_HARNESS_TOKEN: 'synthetic-token-for-isolated-tests', FINANCIAL_PI_HARNESS_POLL_MS: '20' },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  const exited = once(child, 'exit');
  let errors = '';
  child.stderr.on('data', (part) => { errors += part; });
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([finished, exited.then(() => { throw new Error('Worker exited before finish: ' + errors); }),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Synthetic harness timeout: ' + errors)), 12000); })]);
    child.kill('SIGTERM');
    await exited;
    assert.equal(observed.find((item) => item.path.endsWith('/claim'))?.body.protocol_version, 'pi-harness-attempt-v1');
    for (const suffix of ['/chat/completions', '/tools/prepare_workspace', '/heartbeat', '/finish']) {
      const requests = observed.filter((item) => item.path.endsWith(suffix));
      assert.ok(requests.length > 0, 'Missing request ' + suffix);
      for (const request of requests) assert.equal(request.body.attempt, 7);
    }
    for (const request of observed.filter((item) => item.path.endsWith('/chat/completions') || item.path.includes('/tools/'))) {
      assert.equal(request.body.harness_action_id, actionId);
    }
    const reads = observed.filter((item) => item.path.includes('/actions/') && item.query.has('worker_id'));
    assert.ok(reads.length >= 2);
    for (const request of reads) {
      assert.equal(request.query.get('harness_action_id'), actionId);
      assert.equal(request.query.get('attempt'), '7');
    }
    assert.equal(observed.find((item) => item.path.endsWith('/finish'))?.body.outcome, 'succeeded');
  } finally {
    if (timer) clearTimeout(timer);
    if (child.exitCode === null) child.kill('SIGKILL');
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
