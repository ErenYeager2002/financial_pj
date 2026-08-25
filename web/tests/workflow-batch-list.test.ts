import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const root = process.cwd();
const read = (file: string) => fs.readFileSync(path.join(root, file), 'utf8');

test('后台任务页同时读取单日任务和多日期批次', () => {
  const page = read('src/app/dashboard/workflows/page.tsx');
  const server = read('src/features/workflow-agent/api/server.ts');
  const launcher = read('src/features/workflow-agent/components/workflow-launcher.tsx');

  assert.match(page, /listWorkflowBatches\(\)/);
  assert.match(page, /batches=\{batches\}/);
  assert.match(server, /\/api\/workflow-batches\?limit=50/);
  assert.match(launcher, /dashboard\/workflows\/batches/);
});

test('运行中的多日期批次可以取消并返回任务列表', () => {
  const progress = read('src/features/workflow-agent/components/workflow-batch-progress.tsx');
  const route = read('src/app/api/platform/workflow-batches/[batchId]/cancel/route.ts');

  assert.match(progress, /取消整个批次/);
  assert.match(progress, /workflow\.stage === 'applying'/);
  assert.match(progress, /正在写入，不能取消/);
  assert.match(progress, /workflow-batches\/\$\{encodeURIComponent\(batch\.id\)\}\/cancel/);
  assert.match(route, /method:\s*'POST'/);
  assert.match(route, /\/api\/workflow-batches\/\$\{batchId\}\/cancel/);
});
