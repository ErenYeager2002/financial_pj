import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const card = readFileSync(
  new URL('../src/features/workflow-agent/components/zhiyun-credential-card.tsx', import.meta.url),
  'utf8'
);
const launcher = readFileSync(
  new URL('../src/features/workflow-agent/components/workflow-launcher.tsx', import.meta.url),
  'utf8'
);
const route = readFileSync(
  new URL('../src/app/api/platform/service-credentials/[service]/route.ts', import.meta.url),
  'utf8'
);

test('应收核销入口提供带标签和显隐控制的智云账号密码表单', () => {
  assert.match(launcher, /ZhiyunCredentialCard/);
  assert.match(launcher, /requiresZhiyunCredential/);
  assert.match(card, /智云账号/);
  assert.match(card, /智云密码/);
  assert.match(card, /type=\{showPassword \? 'text' : 'password'\}/);
  assert.match(card, /aria-label=\{showPassword \? '隐藏智云密码' : '显示智云密码'\}/);
});

test('凭据只发送到同源代理且保存后清空输入值', () => {
  assert.match(card, /\/api\/platform\/service-credentials\/zhiyun/);
  assert.match(card, /method: 'PUT'/);
  assert.match(card, /setAccount\(''\)/);
  assert.match(card, /setPassword\(''\)/);
  assert.doesNotMatch(card, /localStorage|sessionStorage/);
});

test('开发端代理只允许智云并把凭据交给受保护的后端接口', () => {
  assert.match(route, /value !== 'zhiyun'/);
  assert.match(route, /platformServerRequest<ServiceCredentialRead>/);
  assert.match(route, /\/api\/service-credentials\/\$\{service\}/);
  assert.doesNotMatch(route, /console\.(?:log|error|warn)/);
});

test('智云凭据未配置时应收核销任务不能启动', () => {
  assert.match(launcher, /requiresZhiyunCredential && !zhiyunCredentialConfigured/);
});
