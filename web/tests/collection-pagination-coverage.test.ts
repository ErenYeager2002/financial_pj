import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const activeCollectionFiles = [
  'src/features/admin/components/feature-control-list.tsx',
  'src/features/admin/components/observability-summary.tsx',
  'src/features/admin/components/platform-user-management.tsx',
  'src/features/model-connections/components/model-connection-management.tsx',
  'src/features/run-setup/components/skill-run-setup.tsx',
  'src/features/runs/components/run-detail.tsx',
  'src/features/skills/components/skill-dedicated-user-management.tsx',
  'src/features/skills/components/skill-release-management.tsx',
  'src/features/skills/components/skill-source-management.tsx',
  'src/features/skills/components/workflow-topology.tsx',
  'src/features/task-center/components/task-center-list.tsx',
  'src/features/task-reminders/components/task-reminder-board.tsx',
  'src/features/workbench/components/workbench-overview.tsx',
  'src/features/workflow-agent/components/workflow-agent-panel.tsx',
  'src/features/workflow-agent/components/workflow-batch-progress.tsx',
  'src/features/workflow-agent/components/workflow-fetched-data-dialog.tsx',
  'src/features/workflow-agent/components/workflow-launcher.tsx',
  'src/features/workflow-agent/components/workflow-material-history.tsx'
] as const;

test('active platform business collections use the shared pagination module', async () => {
  for (const file of activeCollectionFiles) {
    const source = await readFile(file, 'utf8');
    assert.match(
      source,
      /PaginatedCollection|useCollectionPagination/,
      `${file} must use the shared collection pagination module`
    );
  }
});

test('文件中心、AI 助手和 Skill 中心只使用纵向滚动', async () => {
  const [files, assistant, skills, filesPage, assistantPage, fileServer, scrollable] =
    await Promise.all([
      readFile('src/features/files/components/file-list.tsx', 'utf8'),
      readFile('src/features/ai-chat/components/assistant-workspace.tsx', 'utf8'),
      readFile('src/features/skills/components/skill-catalog.tsx', 'utf8'),
      readFile('src/app/dashboard/files/page.tsx', 'utf8'),
      readFile('src/app/dashboard/ai-chat/page.tsx', 'utf8'),
      readFile('src/features/files/api/server.ts', 'utf8'),
      readFile('src/components/ui/scrollable-collection.tsx', 'utf8')
    ]);

  for (const source of [files, assistant, skills]) {
    assert.match(source, /ScrollableCollection/);
    assert.doesNotMatch(source, /PaginatedCollection|CollectionPaginationControls|<Pagination/);
  }
  assert.match(filesPage, /listAllFiles\(kind, query\)/);
  assert.doesNotMatch(filesPage, /params\.page|listFiles\(/);
  assert.match(assistantPage, /listAllFiles\('input'\)/);
  assert.match(fileServer, /for \(let page = 2; page <= first\.pages; page \+= 1\)/);
  assert.match(scrollable, /overflow-y-auto/);
  assert.match(scrollable, /role='region'/);
  assert.match(scrollable, /aria-label=\{ariaLabel\}/);
});

test('grid collections use layout capacity and formal tasks always expose server pagination', async () => {
  const [userManagement, taskCenter] = await Promise.all([
    readFile('src/features/admin/components/platform-user-management.tsx', 'utf8'),
    readFile('src/features/task-center/components/task-center-list.tsx', 'utf8')
  ]);

  assert.match(userManagement, /responsivePageSize=\{\{ base: 3, lg: 6 \}\}/);
  assert.match(userManagement, /base: 5,\s+md: 6,\s+lg: 8/);
  assert.match(taskCenter, /aria-label='正式任务当前页，每页最多 5 项'/);
  assert.match(taskCenter, /<Pagination className='pt-2'>/);
  assert.doesNotMatch(taskCenter, /data\.pages > 1/);
  assert.doesNotMatch(taskCenter, /<PaginatedCollection ariaLabel='正式任务'/);
});

test('server-backed platform collections request at most five items per page', async () => {
  const [taskQuery, fetchedDialog, dataTable] = await Promise.all([
    readFile('src/features/task-center/query.ts', 'utf8'),
    readFile('src/features/workflow-agent/components/workflow-fetched-data-dialog.tsx', 'utf8'),
    readFile('src/hooks/use-data-table.ts', 'utf8')
  ]);

  assert.match(taskQuery, /taskCenterApiPath\(query: TaskCenterQuery, pageSize = 5\)/);
  assert.match(fetchedDialog, /const PAGE_SIZE = 5/);
  assert.match(fetchedDialog, /PaginatedTableBody/);
  assert.match(dataTable, /pageSize: 5/);
});
