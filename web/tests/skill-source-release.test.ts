import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

function source(path: string): string {
  return readFileSync(resolve(root, path), 'utf8');
}

test('Skill 源码管理固定使用 Gitee 并要求管理员确认名称匹配', () => {
  const api = source('src/features/admin/api/skill-releases.ts');
  const component = source('src/features/skills/components/skill-source-management.tsx');
  const page = source('src/app/dashboard/skill-governance/page.tsx');

  assert.match(api, /https:\/\/gitee\.com\/Lee157\/finance-skills\.git/);
  assert.match(api, /sourcePath !== `skills\/\$\{skillId\}`/);
  assert.match(component, /按名称发现/);
  assert.match(component, /确认绑定/);
  assert.doesNotMatch(component, /每个 Skill 在同一行显示可用状态/);
  assert.match(component, /buildSkillManagementRows/);
  assert.doesNotMatch(component, /选择要更新的 Skill/);
  assert.match(component, /binding\?\.binding_status === 'bound'/);
  assert.match(component, /item\?\.state === 'disabled'/);
  assert.match(component, /拉取最新代码并更新/);
  assert.match(page, /<SkillSourceManagement initialBindings=\{bindings\}/);
  assert.doesNotMatch(page, /SkillReleaseManagement/);
});

test('已禁用 Skill 可以直接从 Gitee 更新并自动重新启用', () => {
  const api = source('src/features/admin/api/skill-releases.ts');
  const component = source('src/features/skills/components/skill-source-management.tsx');
  const updateRoute = source('src/app/api/platform/admin/skills/[skillId]/update/route.ts');

  assert.match(api, /updateDisabledSkill/);
  assert.match(component, /admin\/skills\/\$\{encodeURIComponent\(skillId\)\}\/update/);
  assert.match(component, /已更新到 \$\{release\.version\}，并重新启用/);
  assert.match(updateRoute, /updateDisabledSkill/);
  assert.doesNotMatch(component, /准备发布版本/);
});

test('旧的异步发布实现不再出现在当前发布维护入口', () => {
  const page = source('src/app/dashboard/skill-governance/page.tsx');
  const rolloutRoute = source(
    'src/app/api/platform/admin/skill-releases/[releaseId]/rollout/route.ts'
  );

  assert.doesNotMatch(page, /skill-release-management/);
  assert.match(rolloutRoute, /startSkillRollout/);
});

test('旧 Gitee 同步脚本只允许只读校验', () => {
  const script = source('../scripts/sync_from_gitee.ps1');
  assert.match(script, /if \(-not \$ValidateOnly\)/);
  assert.match(script, /Direct production sync is disabled/);
});

test('管理员可以独立管理全部平台 Skill 的禁用和启用状态', () => {
  const api = source('src/features/admin/api/skill-releases.ts');
  const component = source('src/features/skills/components/skill-source-management.tsx');
  const availabilityRoute = source(
    'src/app/api/platform/admin/skills/[skillId]/availability/route.ts'
  );
  const availabilityListRoute = source('src/app/api/platform/admin/skills/availability/route.ts');

  assert.match(api, /listSkillAvailability/);
  assert.match(api, /getSkillAvailability/);
  assert.match(api, /transitionSkillAvailability/);
  assert.match(component, /禁用 Skill/);
  assert.match(component, /取消禁用/);
  assert.match(component, /重新启用/);
  assert.match(component, /等待现有任务结束/);
  assert.match(component, /发布恢复失败，保持禁用/);
  assert.match(component, /Skill 可用状态/);
  assert.match(component, /Object\.values\(availability\)/);
  assert.match(availabilityRoute, /export async function GET/);
  assert.match(availabilityRoute, /export async function POST/);
  assert.match(availabilityListRoute, /listSkillAvailability/);
});

test('Skill 可用状态危险操作要求输入对应确认文字', () => {
  const api = source('src/features/admin/api/skill-releases.ts');
  const component = source('src/features/skills/components/skill-source-management.tsx');

  assert.match(api, /confirmation !== expected/);
  assert.match(component, /请输入确认文字/);
  assert.match(component, /`禁用 \$\{availabilityAction\.skillId\}`/);
  assert.match(component, /`启用 \$\{availabilityAction\.skillId\}`/);
});
