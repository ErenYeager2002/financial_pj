import assert from 'node:assert/strict';
import test from 'node:test';
import { createPlatformModel } from '../dist/platform-model-adapter.js';

test('platform model binds workflow connection fields into the gateway payload', async () => {
  const handle = createPlatformModel({
    modelId: 'synthetic-workflow-model',
    gatewayUrl: 'https://platform.synthetic.example/api/assistant/model',
    accessToken: 'platform-session-token',
    gatewayFields: { connection_id: 'connection-1' }
  });
  let captured: Record<string, unknown> | undefined;
  let requestedUrl = '';

  const stream = handle.streamSimple(
    handle.model,
    {
      systemPrompt: '只测试网关字段。',
      messages: [{ role: 'user', content: 'hello' }],
      tools: []
    } as never,
    {
      fetch: async (input) => {
        requestedUrl =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;
        return new Response('data: [DONE]\n\n', {
          status: 200,
          headers: { 'content-type': 'text/event-stream' }
        });
      },
      onPayload: (payload) => {
        captured = payload as Record<string, unknown>;
        return payload;
      }
    }
  );
  for await (const _event of stream) {
    // Consume the provider stream so the payload callback is exercised.
  }

  assert.equal(captured?.model, 'synthetic-workflow-model');
  assert.equal(
    requestedUrl,
    'https://platform.synthetic.example/api/assistant/model/chat/completions'
  );
  assert.equal(captured?.connection_id, 'connection-1');
  assert.equal(captured?.stream, true);
  assert.equal('store' in (captured ?? {}), false);
  assert.equal('prompt_cache_key' in (captured ?? {}), false);
  assert.equal('prompt_cache_retention' in (captured ?? {}), false);
});
