import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

function source(path: string): string {
  return readFileSync(resolve(root, path), 'utf8');
}

test('env-doctor opens a safe platform health summary on the workbench', () => {
  const server = source('src/features/workbench/api/server.ts');
  const page = source('src/app/dashboard/overview/page.tsx');
  const overview = source('src/features/workbench/components/workbench-overview.tsx');
  const experiences = source('src/features/skills/execution-experience.ts');
  const catalog = source('src/features/skills/components/skill-catalog.tsx');

  assert.match(server, /getPlatformHealth/);
  assert.match(server, /\/api\/health/);
  assert.match(page, /Promise\.all/);
  assert.match(page, /health=\{health\}/);
  assert.match(overview, /id='environment-health'/);
  assert.match(overview, /运行环境状态/);
  assert.match(overview, /configured_execution_capacity/);
  assert.match(overview, /registry_errors\?\.length/);
  assert.doesNotMatch(overview, /registry_errors.*\.path|registry_errors.*\.error/);
  assert.match(experiences, /supportHref: '\/dashboard\/overview#environment-health'/);
  assert.match(catalog, /辅助入口/);
});
