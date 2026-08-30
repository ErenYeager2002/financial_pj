import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { stepTypeLabel } from '../src/features/workflows/step-display.ts';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

function source(path: string): string {
  return readFileSync(resolve(root, path), 'utf8');
}

test('runs 的 Query Options 只有 queries.ts 一个来源', () => {
  const queries = source('src/features/runs/api/queries.ts');
  const server = source('src/features/runs/api/server.ts');
  const page = source('src/app/dashboard/runs/[runId]/page.tsx');

  for (const name of ['runQueryOptions', 'runStepsQueryOptions', 'runApprovalsQueryOptions']) {
    assert.match(queries, new RegExp(`function ${name}\\(`));
  }
  assert.doesNotMatch(server, /queryOptions|ServerQueryOptions/);
  assert.doesNotMatch(page, /\.fetchQuery\(/);
  assert.equal(page.match(/void queryClient\.prefetchQuery\(/g)?.length, 3);
  assert.match(page, /<HydrationBoundary/);
  assert.match(page, /<Suspense fallback=/);
});

test('Skill 治理遵循三层数据架构并定时刷新观测数据', () => {
  const types = source('src/features/skill-governance/api/types.ts');
  const service = source('src/features/skill-governance/api/service.ts');
  const queries = source('src/features/skill-governance/api/queries.ts');
  const page = source('src/app/dashboard/skill-governance/page.tsx');
  const data = source('src/features/skill-governance/components/skill-governance-data.tsx');

  assert.match(types, /SkillGovernanceWorkflow/);
  assert.match(service, /platformClientRequest/);
  assert.match(queries, /workflowDefinitionsQueryOptions/);
  assert.match(queries, /observabilityQueryOptions/);
  assert.equal(page.match(/void queryClient\.prefetchQuery\(/g)?.length, 2);
  assert.match(page, /<HydrationBoundary/);
  assert.match(page, /<Suspense fallback=/);
  assert.match(data, /useSuspenseQuery/);
  assert.match(data, /refetchInterval: 60_000/);
  assert.match(data, /refetchIntervalInBackground: false/);
});

test('任务重试使用 mutation、缓存失效和加载反馈', () => {
  const detail = source('src/features/runs/components/run-detail.tsx');

  assert.match(detail, /useMutation\(/);
  assert.match(detail, /invalidateQueries\(\{ queryKey: runKeys\.all \}\)/);
  assert.match(detail, /<LoadingButton/);
  assert.match(detail, /loading=\{retryMutation\.isPending\}/);
  assert.doesNotMatch(detail, /setRetrying|setRetryError/);
});

test('等待确认的普通任务可以从详情页确认执行', () => {
  const detail = source('src/features/runs/components/run-detail.tsx');

  assert.match(detail, /confirmRun/);
  assert.match(detail, /mutationFn: \(\) => confirmRun\(run\.id\)/);
  assert.match(detail, /run\.state === 'waiting_confirmation'/);
  assert.match(detail, /确认并进入队列/);
  assert.match(detail, /loading=\{confirmMutation\.isPending\}/);
});

test('步骤类型中文映射由共享函数提供', () => {
  assert.equal(stepTypeLabel('parameter_validation'), '参数校验');
  assert.equal(stepTypeLabel('controlled_write'), '受控写入');
  assert.equal(stepTypeLabel('future_step'), 'future_step');

  for (const path of [
    'src/features/runs/components/run-detail.tsx',
    'src/features/skills/components/workflow-topology.tsx',
    'src/features/admin/components/observability-summary.tsx'
  ]) {
    assert.match(source(path), /features\/workflows\/step-display/);
  }
});

test('工作台、Skill 中心和 AI 草稿共用 Skill 任务向导', () => {
  const workbench = source('src/features/workbench/components/workbench-overview.tsx');
  const skillDetail = source('src/features/skills/components/skill-detail.tsx');
  const assistant = source('src/features/ai-chat/components/assistant-workspace.tsx');
  const wizard = source('src/features/run-setup/components/skill-run-setup.tsx');
  const skillPage = source('src/app/dashboard/skills/[skillId]/page.tsx');

  assert.match(workbench, /\/dashboard\/skills/);
  assert.match(skillDetail, /<SkillRunSetup/);
  assert.match(assistant, /\/dashboard\/skills\/.*\?draft=/);
  assert.doesNotMatch(assistant, /task-drafts\/.*\/confirm/);
  assert.match(skillPage, /getTaskDraft/);
  assert.match(wizard, /confirmTaskDraftMutation/);
});
