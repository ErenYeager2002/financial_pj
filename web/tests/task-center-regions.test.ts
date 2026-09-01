import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  loadFormalTaskRegion,
  loadTaskReminderRegion,
  type RegionRequest
} from '../src/features/task-center/browser-load.ts';
import { parseTaskCenterQuery } from '../src/features/task-center/query.ts';
import {
  initialRegionDisplay,
  mergeRegionResult,
  settleRegionLoad
} from '../src/features/task-center/region-load.ts';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}

function taskPage(overrides: Record<string, unknown> = {}) {
  return {
    items: [],
    page: 1,
    page_size: 5,
    pages: 0,
    total: 0,
    state_counts: { pending: 0, running: 0, failed: 0, succeeded: 0, cancelled: 0 },
    ...overrides
  };
}

test('提醒失败时正式任务结果仍成功，反向失败也相同', async () => {
  const [tasks, reminders] = await Promise.all([
    settleRegionLoad(async () => ({ total: 2 })),
    settleRegionLoad(async () => {
      throw new Error('private reminder failure');
    })
  ]);
  assert.deepEqual(tasks, { state: 'ready', data: { total: 2 } });
  assert.deepEqual(reminders, { state: 'error' });

  const [failedTasks, readyReminders] = await Promise.all([
    settleRegionLoad(async () => {
      throw new Error('private task failure');
    }),
    settleRegionLoad(async () => ({ reminders: [] }))
  ]);
  assert.deepEqual(failedTasks, { state: 'error' });
  assert.deepEqual(readyReminders, { state: 'ready', data: { reminders: [] } });
});

test('区域失败不泄露异常且重试可独立恢复', async () => {
  let attempts = 0;
  const loader = async () => {
    attempts += 1;
    if (attempts === 1) throw new Error('https://internal.example token=secret');
    return { ok: true };
  };
  assert.deepEqual(await settleRegionLoad(loader), { state: 'error' });
  assert.deepEqual(await settleRegionLoad(loader), { state: 'ready', data: { ok: true } });
});

test('后续刷新失败保留成功数据并显示失败状态，恢复后清除告警', () => {
  const ready = initialRegionDisplay({ state: 'ready' as const, data: { total: 2 } });
  const stale = mergeRegionResult(ready, { state: 'error' });
  assert.deepEqual(stale, {
    result: { state: 'ready', data: { total: 2 } },
    refreshFailed: true
  });
  assert.deepEqual(mergeRegionResult(stale, { state: 'ready', data: { total: 3 } }), {
    result: { state: 'ready', data: { total: 3 } },
    refreshFailed: false
  });
});

test('认证和授权失败继续交给页面级错误处理', async () => {
  await assert.rejects(
    settleRegionLoad(async () => {
      throw { status: 403 };
    }),
    (error: { status?: number }) => error.status === 403
  );
});

test('客户端区域加载器只请求自己的数据源和正式任务页码', async () => {
  const reminderRequests: string[] = [];
  const reminderRequest: RegionRequest = async (input) => {
    reminderRequests.push(input);
    return jsonResponse({ reminders: [], check_failures: [] });
  };
  await loadTaskReminderRegion(reminderRequest);
  assert.deepEqual(reminderRequests, ['/api/platform/task-reminders']);

  const formalRequests: string[] = [];
  const formalRequest: RegionRequest = async (input) => {
    formalRequests.push(input);
    return jsonResponse(taskPage({ total: 2, pages: 1, page: 2 }));
  };
  const query = parseTaskCenterQuery({ page: '2', state: 'failed', skill: 'ar-hexiao-daily' });
  const result = await loadFormalTaskRegion(query, formalRequest);
  assert.equal(formalRequests.length, 1);
  assert.match(formalRequests[0], /page=2/);
  assert.doesNotMatch(formalRequests[0], /view_state|skill_id/);
  assert.equal(result.hasAnyTasks, true);
});

test('客户端重试恢复越界页并把权限失败交给页面', async () => {
  const query = parseTaskCenterQuery({ page: '9', state: 'failed' });
  const recovered = await loadFormalTaskRegion(query, async () =>
    jsonResponse(taskPage({ total: 25, pages: 3, page: 9 }))
  );
  assert.equal(recovered.canonicalHref, '/dashboard/runs?page=3');

  await assert.rejects(
    loadTaskReminderRegion(async () => jsonResponse({}, 403)),
    (error: { status?: number }) => error.status === 403
  );
});

test('两个区域有各自的请求与重试入口', () => {
  const page = readFileSync(new URL('../src/app/dashboard/runs/page.tsx', import.meta.url), 'utf8');
  const regions = readFileSync(
    new URL('../src/features/task-center/components/task-center-regions.tsx', import.meta.url),
    'utf8'
  );
  const browserLoad = readFileSync(
    new URL('../src/features/task-center/browser-load.ts', import.meta.url),
    'utf8'
  );
  assert.match(page, /<TaskReminderRegion/);
  assert.match(page, /<FormalTaskRegion/);
  assert.match(regions, /key=\{queryKey\}/);
  assert.match(browserLoad, /\/api\/platform\/task-reminders/);
  assert.match(browserLoad, /taskCenterBrowserPath\(query\)/);
  assert.match(regions, /role='alert'/);
  assert.match(regions, /当前仍显示上次成功读取的提醒/);
  assert.match(regions, /setAnnouncement\(''\)/);
  assert.match(regions, /重新加载任务提醒/);
  assert.match(regions, /重新加载正式任务/);
});
