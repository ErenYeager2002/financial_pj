import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const component = readFileSync(
  new URL(
    '../src/features/model-connections/components/model-connection-management.tsx',
    import.meta.url
  ),
  'utf8'
);
const serverApi = readFileSync(
  new URL('../src/features/model-connections/api/server.ts', import.meta.url),
  'utf8'
);

test('模型连接页面不回显 API Key 并说明密钥保存方式', () => {
  assert.match(component, /type='password'/);
  assert.match(component, /API Key 加密保存/);
  assert.match(component, /api_key_hint/);
  assert.doesNotMatch(component, /value=\{connection\.api_key\}/);
});

test('模型连接危险操作需要确认并提供明确反馈', () => {
  assert.match(component, /<AlertDialog/);
  assert.match(component, /确认删除/);
  assert.match(component, /aria-live='polite'/);
  assert.match(component, /role='alert'/);
});

test('所有模型连接服务端操作都先验证管理员身份', () => {
  const protectedOperations = serverApi.match(/await requireAdmin\(\);/g) ?? [];
  assert.equal(protectedOperations.length, 6);
});
