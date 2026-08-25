import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const read = (path: string): string => readFileSync(new URL(path, root), 'utf8');

test('task detail exposes a visible cancel action for active workflows', () => {
  const panel = read('src/features/workflow-agent/components/workflow-agent-panel.tsx');

  assert.match(panel, /取消任务/);
  assert.match(panel, /workflows\/\$\{encodeURIComponent\(workflow\.id\)\}\/cancel/);
  assert.match(panel, /取消整个批次/);
  assert.match(panel, /workflow\.stage === 'applying'/);
  assert.match(panel, /正在写入，不能取消/);
});

test('task cancel route validates the workflow id and proxies the request', () => {
  const route = read('src/app/api/platform/workflows/[workflowId]/cancel/route.ts');

  assert.match(route, /UUID\.test\(workflowId\)/);
  assert.match(route, /\/api\/workflows\/\$\{workflowId\}\/cancel/);
  assert.match(route, /method: 'POST'/);
});
