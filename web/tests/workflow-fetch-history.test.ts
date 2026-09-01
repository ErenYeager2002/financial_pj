import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const launcher = readFileSync(
  new URL('../src/features/workflow-agent/components/workflow-launcher.tsx', import.meta.url),
  'utf8'
);
const singleRoute = readFileSync(
  new URL('../src/app/api/platform/workflows/start/route.ts', import.meta.url),
  'utf8'
);
const batchRoute = readFileSync(
  new URL('../src/app/api/platform/workflow-batches/start/route.ts', import.meta.url),
  'utf8'
);

test('新建任务只用取数包 ID 发起回放', () => {
  assert.match(launcher, /fetched_bundle_id: selectedFetchedBundleId/);
  assert.doesNotMatch(launcher, /snapshot_workflow_id/);
  assert.match(singleRoute, /fetched_bundle_id/);
  assert.match(batchRoute, /fetched_bundle_id/);
  assert.match(singleRoute, /snapshot_workflow_id: legacyWorkflowId/);
  assert.match(batchRoute, /snapshot_workflow_id: legacyWorkflowId/);
});

test('创建应收核销任务只展示可回放取数包', () => {
  assert.match(launcher, /availability === 'replayable_bundle'/);
  assert.match(launcher, /使用可回放取数包/);
  assert.doesNotMatch(launcher, /历史取数预览/);
  assert.doesNotMatch(launcher, /历史预览/);
  assert.doesNotMatch(launcher, /原始文件已清理，不可回放/);
  assert.match(launcher, /当前没有可回放取数包/);
  assert.match(launcher, /正在读取取数记录/);
});
