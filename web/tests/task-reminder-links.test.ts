import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

import {
  actionableReminderDates,
  taskReminderWorkflowHref
} from '../src/features/task-reminders/links.ts';

test('任务提醒链接保留所有未成功日期', () => {
  const href = taskReminderWorkflowHref('ar-hexiao-daily', [
    '2026-08-21',
    '2026-08-22',
    '2026-08-24'
  ]);
  const url = new URL(href, 'http://localhost');

  assert.equal(url.pathname, '/dashboard/workflows');
  assert.equal(url.searchParams.get('skill'), 'ar-hexiao-daily');
  assert.deepEqual(url.searchParams.getAll('date'), ['2026-08-21', '2026-08-22', '2026-08-24']);
  assert.equal(url.searchParams.get('reminder'), '1');
});

test('整组处理排除已经关联正式任务的日期', () => {
  assert.deepEqual(
    actionableReminderDates([
      { business_date: '2026-08-21', state: 'pending' },
      { business_date: '2026-08-22', state: 'in_progress' },
      { business_date: '2026-08-23', state: 'reopened' }
    ]),
    ['2026-08-21', '2026-08-23']
  );
});

test('任务创建页消费提醒中的 Skill 和全部重复日期参数', () => {
  const page = fs.readFileSync(
    path.join(process.cwd(), 'src/app/dashboard/workflows/page.tsx'),
    'utf8'
  );

  assert.match(page, /typeof params\.skill === 'string' \? params\.skill : ''/);
  assert.match(
    page,
    /Array\.isArray\(params\.date\) \? params\.date : params\.date \? \[params\.date\] : \[\]/
  );
  assert.match(page, /initialSkillId=\{selectedSkillId\}/);
  assert.match(page, /initialDates=\{initialDates\}/);
});
