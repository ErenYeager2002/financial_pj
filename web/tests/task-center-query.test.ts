import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  hasTaskCenterUnsupportedParams,
  parseTaskCenterQuery,
  taskCenterApiPath,
  taskCenterHref,
  taskCenterPageRedirect
} from '../src/features/task-center/query.ts';
import {
  taskCenterActionLabel,
  taskCenterEmptyState,
  taskCenterResultAnnouncement,
  taskCenterStateLabel,
  taskCenterTypeLabel
} from '../src/features/task-center/presentation.ts';

test('我的任务查询只保留页码并忽略旧筛选参数', () => {
  assert.deepEqual(
    parseTaskCenterQuery({
      page: '-3',
      state: 'failed',
      type: 'workflow_batch',
      skill: 'ar-hexiao-daily',
      business_from: '2026-08-01',
      updated_to: '2026-08-24T18:00'
    }),
    { page: 1 }
  );
  assert.deepEqual(parseTaskCenterQuery({ page: '999999999' }), { page: 100_000 });
  assert.deepEqual(parseTaskCenterQuery({ page: ['3', '4'] }), { page: 3 });
  assert.equal(hasTaskCenterUnsupportedParams({ page: '2' }), false);
  assert.equal(hasTaskCenterUnsupportedParams({ page: '2', state: 'failed' }), true);
});

test('正式任务请求和翻页链接只携带分页参数', () => {
  const query = parseTaskCenterQuery({ page: '2', state: 'running', skill: 'ignored' });
  const api = new URL(taskCenterApiPath(query), 'http://backend');
  assert.equal(api.pathname, '/api/task-center');
  assert.equal(api.searchParams.get('page'), '2');
  assert.equal(api.searchParams.get('page_size'), '5');
  assert.equal([...api.searchParams.keys()].toSorted().join(','), 'page,page_size');

  const next = new URL(taskCenterHref(query, 3), 'http://localhost');
  assert.equal(next.pathname, '/dashboard/runs');
  assert.equal(next.searchParams.get('page'), '3');
  assert.equal([...next.searchParams.keys()].join(','), 'page');
});

test('越界页回到最后一个有效页', () => {
  const query = parseTaskCenterQuery({ page: '9', state: 'failed' });
  assert.equal(taskCenterPageRedirect(query, 3), '/dashboard/runs?page=3');
  assert.equal(taskCenterPageRedirect(query, 9), null);
  assert.equal(taskCenterPageRedirect(query, 0), null);
});

test('空态只区分没有任务和页码变化', () => {
  assert.equal(taskCenterEmptyState(false).title, '暂无正式任务');
  assert.equal(taskCenterEmptyState(false).action, '创建任务');
  assert.equal(taskCenterEmptyState(true).title, '当前页没有任务');
  assert.equal(taskCenterEmptyState(true).action, '返回第一页');
});

test('三种任务类型、中文状态和下一步操作具有统一语义', () => {
  assert.equal(taskCenterTypeLabel('run', 'other-skill'), '普通任务');
  assert.equal(taskCenterTypeLabel('workflow', 'ar-hexiao-daily'), '应收核销日期');
  assert.equal(taskCenterTypeLabel('workflow_batch', 'ar-hexiao-daily'), '应收核销批次');
  assert.equal(taskCenterStateLabel('pending'), '待处理');
  assert.equal(taskCenterStateLabel('running'), '执行中');
  assert.equal(taskCenterActionLabel('failed'), '查看失败原因');
  assert.equal(taskCenterActionLabel('succeeded'), '查看结果');
  assert.equal(taskCenterResultAnnouncement(5, 27, 2), '第 2 页显示 5 条任务，共 27 条任务。');
});

test('我的任务保留统一数据源、分页和提醒，但不提供筛选', () => {
  const page = readFileSync(new URL('../src/app/dashboard/runs/page.tsx', import.meta.url), 'utf8');
  const server = readFileSync(
    new URL('../src/features/task-center/api/server.ts', import.meta.url),
    'utf8'
  );
  const list = readFileSync(
    new URL('../src/features/task-center/components/task-center-list.tsx', import.meta.url),
    'utf8'
  );

  assert.match(page, /getTaskCenterPage\(query\)/);
  assert.match(page, /hasTaskCenterUnsupportedParams\(rawQuery\)/);
  assert.match(page, /<TaskReminderRegion/);
  assert.match(page, /<FormalTaskRegion/);
  assert.doesNotMatch(page, /listRuns|listWorkflowSessions|listWorkflowBatches|ArTaskList/);
  assert.match(server, /platformServerRequest<TaskCenterPage>\(taskCenterApiPath\(query\)\)/);
  assert.match(list, /data\.state_counts\.pending/);
  assert.match(list, /data\.state_counts\.failed/);
  assert.doesNotMatch(list, /TaskCenterFilters|应用筛选|清除筛选/);
  assert.doesNotMatch(list, /name='state'|name='type'|name='skill'|business_from|updated_to/);
  assert.match(list, /taskCenterHref\(query, Math\.min/);
  assert.match(list, /<Pagination className='pt-2'>/);
  assert.doesNotMatch(list, /data\.pages > 1/);
  assert.doesNotMatch(list, /<PaginatedCollection ariaLabel='正式任务'/);
});
