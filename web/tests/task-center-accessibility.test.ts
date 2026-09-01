import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync(new URL('../src/app/dashboard/runs/page.tsx', import.meta.url), 'utf8');
const pageContainer = readFileSync(
  new URL('../src/components/layout/page-container.tsx', import.meta.url),
  'utf8'
);
const heading = readFileSync(new URL('../src/components/ui/heading.tsx', import.meta.url), 'utf8');
const list = readFileSync(
  new URL('../src/features/task-center/components/task-center-list.tsx', import.meta.url),
  'utf8'
);
const regions = readFileSync(
  new URL('../src/features/task-center/components/task-center-regions.tsx', import.meta.url),
  'utf8'
);
const reminders = readFileSync(
  new URL('../src/features/task-reminders/components/task-reminder-board.tsx', import.meta.url),
  'utf8'
);

test('我的任务使用唯一一级标题且区域使用二级标题', () => {
  assert.match(page, /headingLevel=\{1\}/);
  assert.match(pageContainer, /level=\{headingLevel\}/);
  assert.match(heading, /level === 1 \? 'h1' : 'h2'/);
  assert.match(list, /<h2[^>]*>正式任务<\/h2>/);
  assert.match(reminders, /<h2[^>]*>任务提醒<\/h2>/);
  assert.doesNotMatch(list, /<h1/);
  assert.doesNotMatch(reminders, /<h1/);
});

test('任务条目在小屏使用同一张卡片展示关键信息和操作', () => {
  assert.match(list, /<article className='grid gap-4 rounded-xl border p-4 md:grid-cols-/);
  assert.match(list, /taskCenterTypeLabel/);
  assert.match(list, /businessDateLabel/);
  assert.match(list, /taskCenterStateLabel/);
  assert.match(list, /item\.progress/);
  assert.match(list, /taskCenterActionLabel/);
  assert.match(list, /item\.error_summary/);
  assert.doesNotMatch(list, /<Table|overflow-x-auto|hidden md:/);
});

test('进度、结果变化、错误和刷新成功具有可访问语义', () => {
  assert.match(list, /aria-label=\{`\$\{item\.skill_name\}进度 \$\{item\.progress\}%`\}/);
  assert.match(regions, /role='status' aria-live='polite'/);
  assert.match(regions, /setResultAnnouncement\(\s*taskCenterResultAnnouncement/);
  assert.match(regions, /<Card role='alert'/);
  assert.match(regions, /任务提醒已重新加载/);
  assert.match(regions, /正式任务已重新加载/);
  assert.match(reminders, /role='alert'/);
});

test('分页、固定补查入口和详情入口保持键盘可操作', () => {
  assert.doesNotMatch(list, /TaskCenterFilters|应用筛选|清除筛选/);
  assert.match(list, /tabIndex=\{data\.page <= 1 \? -1 : undefined\}/);
  assert.match(list, /tabIndex=\{data\.page >= data\.pages \? -1 : undefined\}/);
  assert.doesNotMatch(reminders, /<details|<summary/);
  assert.match(reminders, /<section[^>]*aria-labelledby='manual-check-date-title'/);
  assert.match(reminders, /htmlFor='task-reminder-manual-date'/);
  assert.match(reminders, /处理这些日期/);
  assert.match(list, /href=\{item\.detail_href\}/);
});
