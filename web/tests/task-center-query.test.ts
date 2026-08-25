import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  parseTaskCenterQuery,
  taskCenterApiPath,
  taskCenterHref,
  taskCenterPageRedirect
} from '../src/features/task-center/query.ts';
import {
  taskCenterActionLabel,
  taskCenterEmptyState,
  taskCenterQueryContext,
  taskCenterResultAnnouncement,
  taskCenterStateLabel,
  taskCenterTypeLabel
} from '../src/features/task-center/presentation.ts';

test('任务中心查询只保留受支持参数并规范页码', () => {
  assert.deepEqual(
    parseTaskCenterQuery({
      page: '-3',
      state: 'failed',
      type: 'workflow_batch',
      skill: 'ar-hexiao-daily',
      business_from: '2026-08-01',
      business_to: '2026-08-24',
      updated_from: '2026-08-01T09:10',
      updated_to: '2026-08-24T18:00'
    }),
    {
      page: 1,
      state: 'failed',
      type: 'workflow_batch',
      skill: 'ar-hexiao-daily',
      businessFrom: '2026-08-01',
      businessTo: '2026-08-24',
      updatedFrom: '2026-08-01T09:10',
      updatedTo: '2026-08-24T18:00'
    }
  );
  assert.equal(parseTaskCenterQuery({ state: 'secret', type: 'other' }).state, '');
  assert.equal(parseTaskCenterQuery({ state: 'secret', type: 'other' }).type, '');
});

test('后端查询与翻页链接保留全部筛选条件', () => {
  const query = parseTaskCenterQuery({
    page: '2',
    state: 'running',
    type: 'workflow',
    skill: 'ar-hexiao-daily',
    business_from: '2026-08-01',
    business_to: '2026-08-24',
    updated_from: '2026-08-01T09:10',
    updated_to: '2026-08-24T18:00'
  });
  const api = new URL(taskCenterApiPath(query), 'http://backend');
  assert.equal(api.pathname, '/api/task-center');
  assert.equal(api.searchParams.get('page'), '2');
  assert.equal(api.searchParams.get('page_size'), '20');
  assert.equal(api.searchParams.get('view_state'), 'running');
  assert.equal(api.searchParams.get('item_type'), 'workflow');
  assert.equal(api.searchParams.get('skill_id'), 'ar-hexiao-daily');
  assert.equal(api.searchParams.get('business_date_from'), '2026-08-01');
  assert.equal(api.searchParams.get('business_date_to'), '2026-08-24');
  assert.equal(api.searchParams.get('updated_from'), '2026-08-01T09:10:00+08:00');
  assert.equal(api.searchParams.get('updated_to'), '2026-08-24T18:00:00+08:00');

  const next = new URL(taskCenterHref(query, 3), 'http://localhost');
  assert.equal(next.searchParams.get('page'), '3');
  assert.equal(next.searchParams.get('state'), 'running');
  assert.equal(next.searchParams.get('type'), 'workflow');
  assert.equal(next.searchParams.get('business_from'), '2026-08-01');
  assert.equal(next.searchParams.get('updated_to'), '2026-08-24T18:00');
});

test('越界页保留筛选并回到最后一个有效页', () => {
  const query = parseTaskCenterQuery({ page: '9', state: 'failed', skill: 'ar-hexiao-daily' });
  assert.equal(
    taskCenterPageRedirect(query, 3),
    '/dashboard/runs?page=3&state=failed&skill=ar-hexiao-daily'
  );
  assert.equal(taskCenterPageRedirect(query, 9), null);
  assert.equal(taskCenterPageRedirect(query, 0), null);
});

test('空态区分从未创建任务和当前筛选无结果', () => {
  assert.equal(taskCenterEmptyState(false, true).title, '暂无正式任务');
  assert.equal(taskCenterEmptyState(false, true).action, '创建任务');
  assert.equal(taskCenterEmptyState(false, false).title, '暂无正式任务');
  assert.equal(taskCenterEmptyState(false, false).action, '创建任务');
  assert.equal(taskCenterEmptyState(true, true).title, '当前筛选没有匹配任务');
});

test('非法日期、反向范围、重复参数和超大页码被安全规范', () => {
  const query = parseTaskCenterQuery({
    page: '999999999',
    state: ['failed', 'running'],
    business_from: '2026-08-24',
    business_to: '2026-02-30',
    updated_from: '2026-08-25T29:80',
    updated_to: '2026-08-01T09:10'
  });
  assert.equal(query.page, 100_000);
  assert.equal(query.state, 'failed');
  assert.equal(query.businessFrom, '2026-08-24');
  assert.equal(query.businessTo, '');
  assert.equal(query.updatedFrom, '');
  assert.equal(query.updatedTo, '2026-08-01T09:10');

  const reversed = parseTaskCenterQuery({
    business_from: '2026-08-24',
    business_to: '2026-08-01',
    updated_from: '2026-08-24T09:10',
    updated_to: '2026-08-01T09:10'
  });
  assert.equal(reversed.businessFrom, '');
  assert.equal(reversed.businessTo, '');
  assert.equal(reversed.updatedFrom, '');
  assert.equal(reversed.updatedTo, '');
});

test('三种任务类型、中文状态和下一步操作具有统一语义', () => {
  assert.equal(taskCenterTypeLabel('run', 'other-skill'), '普通任务');
  assert.equal(taskCenterTypeLabel('workflow', 'ar-hexiao-daily'), '应收核销日期');
  assert.equal(taskCenterTypeLabel('workflow_batch', 'ar-hexiao-daily'), '应收核销批次');
  assert.equal(taskCenterStateLabel('pending'), '待处理');
  assert.equal(taskCenterStateLabel('running'), '执行中');
  assert.equal(taskCenterActionLabel('failed'), '查看失败原因');
  assert.equal(taskCenterActionLabel('succeeded'), '查看结果');
  assert.equal(
    taskCenterResultAnnouncement(7, 27, 2, '状态 失败'),
    '状态 失败。第 2 页显示 7 条任务，共 27 条匹配结果。'
  );
  assert.equal(
    taskCenterQueryContext(parseTaskCenterQuery({ state: 'failed', business_from: '2026-08-01' })),
    '状态 失败，业务日期从 2026-08-01'
  );
  assert.notEqual(
    taskCenterResultAnnouncement(
      7,
      27,
      1,
      taskCenterQueryContext(parseTaskCenterQuery({ state: 'failed' }))
    ),
    taskCenterResultAnnouncement(
      7,
      27,
      1,
      taskCenterQueryContext(parseTaskCenterQuery({ state: 'running' }))
    )
  );
});

test('我的任务页面只使用统一正式任务数据源并保留独立提醒区', () => {
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
  assert.match(page, /<TaskReminderRegion/);
  assert.match(page, /<FormalTaskRegion/);
  assert.doesNotMatch(page, /listRuns|listWorkflowSessions|listWorkflowBatches|ArTaskList/);
  assert.match(server, /platformServerRequest<TaskCenterPage>\(taskCenterApiPath\(query\)\)/);
  assert.match(list, /data\.state_counts\.pending/);
  assert.match(list, /data\.state_counts\.failed/);
  assert.match(list, /name='business_from'/);
  assert.match(list, /name='updated_to'/);
  assert.match(list, /taskCenterHref\(query, Math\.min/);
});
