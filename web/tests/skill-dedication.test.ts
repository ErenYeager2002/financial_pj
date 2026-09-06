import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

function source(path: string): string {
  return readFileSync(resolve(root, path), 'utf8');
}

test('管理员治理页加载专属员工数据并提供员工列表', () => {
  const page = source('src/app/dashboard/skill-governance/page.tsx');
  const component = source('src/features/skills/components/skill-dedicated-user-management.tsx');

  assert.match(page, /listSkillDedications/);
  assert.match(page, /listAdminUsers/);
  assert.match(page, /listSkillCatalog/);
  assert.ok(page.indexOf('SkillDedicatedUserManagement') < page.indexOf('SkillSourceManagement'));
  assert.match(component, /Skill 专属员工/);
  assert.match(component, /按 Skill ID 或名称筛选/);
  assert.match(component, /专属员工/);
  assert.match(component, /员工状态/);
  assert.match(component, /user\.status === 'active'/);
  assert.match(component, /user\.role === 'finance_user'/);
});

test('设置、更换和清除专属员工使用管理员 BFF 接口', () => {
  const api = source('src/features/admin/api/skill-dedications.ts');
  const collectionRoute = source('src/app/api/platform/admin/skill-dedications/route.ts');
  const itemRoute = source('src/app/api/platform/admin/skill-dedications/[skillId]/route.ts');
  const component = source('src/features/skills/components/skill-dedicated-user-management.tsx');

  assert.match(api, /listSkillDedications/);
  assert.match(api, /setSkillDedication/);
  assert.match(api, /clearSkillDedication/);
  assert.match(api, /session\.role !== 'skill_admin'/);
  assert.match(collectionRoute, /export async function GET/);
  assert.match(collectionRoute, /listSkillDedications/);
  assert.match(itemRoute, /export async function PUT/);
  assert.match(itemRoute, /export async function DELETE/);
  assert.match(component, /method: 'PUT'/);
  assert.match(component, /method: 'DELETE'/);
  assert.match(component, /确认清除/);
  assert.match(component, /已停用/);
});

test('管理员 Skill 展示专属员工，员工目录不读取管理员标记', () => {
  const catalog = source('src/features/skills/components/skill-catalog.tsx');
  const detail = source('src/features/skills/components/skill-detail.tsx');
  const skillsPage = source('src/app/dashboard/skills/page.tsx');
  const detailPage = source('src/app/dashboard/skills/[skillId]/page.tsx');

  assert.match(catalog, /adminDedications\?: Record<string, SkillDedication>/);
  assert.match(catalog, /专属：/);
  assert.match(catalog, /（已停用）/);
  assert.match(detail, /adminDedication\?: SkillDedication/);
  assert.match(detail, /专属：/);
  assert.match(skillsPage, /platformServerRequest<PlatformSession>\('\/api\/session'\)/);
  assert.match(skillsPage, /session\.role === 'skill_admin' \? listSkillDedications\(\)/);
  assert.match(skillsPage, /listSkillSummaries\(\)/);
  assert.doesNotMatch(skillsPage, /listSkillCatalog\(\)/);
  assert.match(detailPage, /platformServerRequest<PlatformSession>\('\/api\/session'\)/);
  assert.match(detailPage, /session\.role === 'skill_admin' \? listSkillDedications\(\)/);
  assert.match(skillsPage, /adminDedications={adminDedications}/);
  assert.match(detailPage, /adminDedication={adminDedication}/);
});
