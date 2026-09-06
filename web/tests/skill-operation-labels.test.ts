import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

function source(path: string): string {
  return readFileSync(resolve(root, path), 'utf8');
}

test('Skill 目录卡片展示员工安全标签，详情页不重复展示目录元数据', () => {
  const catalog = source('src/features/skills/components/skill-catalog-card.tsx');
  const detail = source('src/features/skills/components/skill-detail.tsx');

  assert.match(catalog, /skill\.operation_labels\.slice\(0, 2\)/);
  assert.match(catalog, /skillRiskLabels\(skill\)/);
  assert.match(catalog, /line-clamp-2/);
  assert.doesNotMatch(detail, /skill\.operation_labels|skill\.categories|estimated_minutes/);
  assert.equal(detail.match(/<Badge/g)?.length, 1);
  assert.match(catalog, /专属：/);
  assert.match(detail, /专属：/);
});

test('员工页面不读取外部系统地址或运行画像原始字段', () => {
  const catalog = source('src/features/skills/components/skill-catalog-card.tsx');
  const detail = source('src/features/skills/components/skill-detail.tsx');

  assert.doesNotMatch(catalog, /operational_profile|external_sources|network_targets/);
  assert.doesNotMatch(detail, /operational_profile|external_sources|network_targets/);
});
