import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  manualCheckDateBounds,
  taskReminderBoardMode,
  taskReminderBoardVisibility
} from '../src/features/task-reminders/task-reminder-board-presentation.ts';

test('提醒区区分空闲、待办和仅检查失败状态', () => {
  assert.equal(taskReminderBoardMode([], []), 'idle');
  assert.equal(taskReminderBoardMode([{ id: 'reminder-1' }], []), 'pending');
  assert.equal(taskReminderBoardMode([], [{ id: 'failure-1' }]), 'failure');
  assert.equal(taskReminderBoardMode([{ id: 'reminder-1' }], [{ id: 'failure-1' }]), 'pending');
});

test('提醒区组合状态不会混入错误空态', () => {
  assert.deepEqual(taskReminderBoardVisibility([], []), {
    mode: 'idle',
    showIdle: true,
    showPending: false,
    showFailures: false
  });
  assert.deepEqual(taskReminderBoardVisibility([{ id: 'pending' }], []), {
    mode: 'pending',
    showIdle: false,
    showPending: true,
    showFailures: false
  });
  assert.deepEqual(taskReminderBoardVisibility([], [{ id: 'failed' }]), {
    mode: 'failure',
    showIdle: false,
    showPending: false,
    showFailures: true
  });
});

test('手动补查日期限制为昨天起向前 31 天', () => {
  assert.deepEqual(manualCheckDateBounds(new Date(2026, 7, 25, 9, 10)), {
    min: '2026-07-25',
    max: '2026-08-24'
  });
});

test('组件固定展示补查入口、待办主操作和可访问错误反馈', () => {
  const source = readFileSync(
    new URL('../src/features/task-reminders/components/task-reminder-board.tsx', import.meta.url),
    'utf8'
  );

  assert.doesNotMatch(source, /<details|<summary/);
  assert.match(source, /<section[^>]*aria-labelledby='manual-check-date-title'/);
  assert.match(source, /<h2 id='manual-check-date-title'/);
  assert.match(source, /手动补查日期/);
  assert.match(source, /处理这些日期/);
  assert.match(source, /role='alert'/);
  assert.match(source, /failure\.error_message/);
  assert.match(source, /<Card[\s\S]*role='alert'[\s\S]*aria-live='polite'/);
  assert.match(source, /min=\{dateBounds\.min\}/);
  assert.match(source, /max=\{dateBounds\.max\}/);
  assert.doesNotMatch(source, /setManualDate\(''\)/);
  assert.match(source, /data\.resolved_count/);
  assert.match(source, /清理已处理成功/);
  assert.match(source, /method: 'DELETE'/);

  const route = readFileSync(
    new URL('../src/app/api/platform/task-reminders/route.ts', import.meta.url),
    'utf8'
  );
  const server = readFileSync(
    new URL('../src/features/task-reminders/api/server.ts', import.meta.url),
    'utf8'
  );
  assert.match(route, /export async function DELETE/);
  assert.match(server, /\/api\/task-reminders\/resolved/);
});

test('待处理日期使用共享分页和滚动区', () => {
  const source = readFileSync(
    new URL('../src/features/task-reminders/components/task-reminder-board.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /<PaginatedCollection/);
  assert.match(source, /ariaLabel=\{`\$\{first\.skill_name\}待处理日期`\}/);
  assert.match(source, /role='listitem'/);
});
