import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { createClientId } from '../src/lib/client-id.ts';

test('局域网 HTTP 环境没有 randomUUID 时仍能生成 UUID', () => {
  const source = {
    getRandomValues<T extends ArrayBufferView>(values: T): T {
      const bytes = new Uint8Array(values.buffer, values.byteOffset, values.byteLength);
      bytes.forEach((_, index) => {
        bytes[index] = index;
      });
      return values;
    }
  };

  assert.equal(createClientId(source), '00010203-0405-4607-8809-0a0b0c0d0e0f');
});

test('浏览器提供 randomUUID 时优先使用原生实现', () => {
  assert.equal(
    createClientId({ randomUUID: () => '11111111-1111-4111-8111-111111111111' }),
    '11111111-1111-4111-8111-111111111111'
  );
});

test('客户端源码不再直接调用安全上下文限定的 crypto.randomUUID', () => {
  const setup = readFileSync(
    new URL('../src/features/run-setup/components/skill-run-setup.tsx', import.meta.url),
    'utf8'
  );
  const assistant = readFileSync(
    new URL('../src/features/ai-chat/components/assistant-workspace.tsx', import.meta.url),
    'utf8'
  );

  assert.doesNotMatch(`${setup}\n${assistant}`, /crypto\.randomUUID\s*\(/);
});
