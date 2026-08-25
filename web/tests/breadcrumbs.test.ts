import assert from 'node:assert/strict';
import test from 'node:test';

import { buildBreadcrumbs } from '../src/lib/breadcrumbs.ts';

test('工作台面包屑只有一个工作台条目且 key 对应的链接唯一', () => {
  assert.deepEqual(buildBreadcrumbs('/dashboard/overview'), [
    { title: '工作台', link: '/dashboard/overview' }
  ]);
});

test('应收核销单日详情从我的任务进入并保留详情层级', () => {
  assert.deepEqual(buildBreadcrumbs('/dashboard/workflows/task-1'), [
    { title: '工作台', link: '/dashboard/overview' },
    { title: '我的任务', link: '/dashboard/runs' },
    { title: '任务详情', link: '/dashboard/workflows/task-1' }
  ]);
});

test('应收核销创建页显示创建语义', () => {
  assert.deepEqual(
    buildBreadcrumbs('/dashboard/workflows', (path) =>
      path === '/dashboard/workflows' ? '创建应收核销任务' : undefined
    ),
    [
      { title: '工作台', link: '/dashboard' },
      { title: '创建应收核销任务', link: '/dashboard/workflows' }
    ]
  );
});

test('应收核销批次详情从我的任务进入并保留详情层级', () => {
  assert.deepEqual(buildBreadcrumbs('/dashboard/workflows/batches/batch-1'), [
    { title: '工作台', link: '/dashboard/overview' },
    { title: '我的任务', link: '/dashboard/runs' },
    { title: '批次详情', link: '/dashboard/workflows/batches/batch-1' }
  ]);
});
