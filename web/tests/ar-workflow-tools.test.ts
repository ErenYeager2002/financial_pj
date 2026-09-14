import assert from 'node:assert/strict';
import test from 'node:test';
import { createArWorkflowTools } from '../src/features/ai-chat/ar-workflow-tools.ts';

test('AR tools read platform materials without chat file IDs and bind mutations to actual user message', async () => {
  const calls: { path: string; body?: Record<string, unknown> }[] = [];
  const tools = createArWorkflowTools({ sessionId: 'owned-session', message: '再跑一次' }, async (path, body) => {
    calls.push({ path, body });
    return { ready: true, plan_id: 'prepared-plan' };
  });
  const tool = (name: string) => tools.find((item) => item.name === name)!;
  await tool('inspect_ar_materials').execute('read', { skill_id: 'ar-hexiao-daily-lab' });
  assert.equal(calls[0].body, undefined);
  assert.equal(calls[0].path, '/api/assistant/ar/materials?skill_id=ar-hexiao-daily-lab');
  await tool('prepare_ar_workflow').execute('prepare', {
    skill_id: 'ar-hexiao-daily-lab', reconciliation_dates: ['2026-08-20'],
    authorization_quote: '再跑一次', session_id: 'invented', message: 'invented'
  });
  assert.equal(calls[1].body?.session_id, 'owned-session');
  assert.equal(calls[1].body?.message, '再跑一次');
  await tool('start_ar_workflow').execute('start', { plan_id: 'prepared-plan', skill_id: 'unrelated' });
  assert.deepEqual(calls[2].body, { plan_id: 'prepared-plan', session_id: 'owned-session', message: '再跑一次' });
  await tool('get_ar_request_status').execute('status', {});
  assert.equal(calls[3].body, undefined);
});

test('errors are surfaced without retrying task creation', async () => {
  let count = 0;
  const tools = createArWorkflowTools({ sessionId: 's', message: '执行' }, async () => {
    count++;
    throw new Error('启动结果未知');
  });
  const start = tools.find((item) => item.name === 'start_ar_workflow')!;
  await assert.rejects(start.execute('start', { plan_id: 'p' }), /启动结果未知/);
  assert.equal(count, 1);
});
