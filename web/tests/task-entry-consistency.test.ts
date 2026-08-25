import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const root = process.cwd();
const read = (file: string) => fs.readFileSync(path.join(root, file), 'utf8');

test('任务创建页和详情页使用统一的任务名称', () => {
  const creationPage = read('src/app/dashboard/workflows/page.tsx');
  const detailPage = read('src/app/dashboard/workflows/[workflowId]/page.tsx');
  const batchPage = read('src/app/dashboard/workflows/batches/[batchId]/page.tsx');

  assert.match(creationPage, /pageTitle='创建应收核销任务'/);
  assert.match(detailPage, /pageTitle='应收核销任务详情'/);
  assert.match(batchPage, /pageTitle='应收核销批次详情'/);
});

test('独立任务和批次任务返回我的任务，批次子任务仍返回所属批次', () => {
  const panel = read('src/features/workflow-agent/components/workflow-agent-panel.tsx');
  const batchProgress = read('src/features/workflow-agent/components/workflow-batch-progress.tsx');

  assert.match(panel, /workflow\.batch_id[\s\S]*: '\/dashboard\/runs'/);
  assert.match(panel, /dashboard\/workflows\/batches/);
  assert.match(batchProgress, /href='\/dashboard\/runs' aria-label='返回任务列表'/);
});

test('任务入口页面不再向用户展示后台任务分类', () => {
  const userFacingSources = [
    'src/app/dashboard/workflows/page.tsx',
    'src/app/dashboard/workflows/[workflowId]/page.tsx',
    'src/app/dashboard/workflows/batches/[batchId]/page.tsx',
    'src/features/workflow-agent/components/workflow-launcher.tsx',
    'src/features/skills/components/skill-detail.tsx',
    'src/features/workflow-agent/workflow-flow.ts',
    'src/features/workflow-agent/components/workflow-progress-card.tsx',
    'src/app/dashboard/runs/page.tsx'
  ].map(read);

  for (const source of userFacingSources) {
    assert.doesNotMatch(source, /后台任务/);
  }
});
