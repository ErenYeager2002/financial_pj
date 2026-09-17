import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clearSkillCatalogFilters,
  DEFAULT_SKILL_CATALOG_FILTERS,
  filterSkillCatalog,
  hasSkillCatalogFilters,
  skillCatalogActionFor,
  skillCatalogDedicationOptions,
  skillRiskLabels,
  sortSkillCatalog
} from '../src/features/skills/skill-catalog-state.ts';
import type { SkillSummary } from '../src/features/platform-api/types';

function skill(overrides: Partial<SkillSummary> = {}): SkillSummary {
  const base: SkillSummary = {
    id: 'skill-a',
    name: '应收核销',
    version: '1.0.0',
    status: 'published',
    description: '按日期核对到账记录',
    categories: ['应收'],
    tags: ['日清'],
    operation_labels: ['读取明细', '写入副本'],
    estimated_minutes: 10,
    output_summary: '核销清单和报告',
    action_label: '开始核销',
    popular: false,
    execution_mode: 'standard',
    interaction_mode: 'form',
    catalog_module: 'tools',
    execution_modes: ['workflow'],
    default_execution_mode: 'workflow',
    risk: {
      level: 'write',
      requires_confirmation: true,
      requires_approval: false,
      modifies_uploaded_files: false
    },
    ...overrides
  };
  return base;
}

test('Skill 目录搜索覆盖名称、描述、标签和 operation_labels', () => {
  const candidates = [
    skill({ id: 'name-match', name: '银行对账' }),
    skill({ id: 'description-match', description: '生成月度汇总' }),
    skill({ id: 'tag-match', tags: ['月报'] }),
    skill({ id: 'operation-match', operation_labels: ['导出结果'] })
  ];

  for (const [query, expectedId] of [
    ['银行', 'name-match'],
    ['汇总', 'description-match'],
    ['月报', 'tag-match'],
    ['导出', 'operation-match']
  ]) {
    assert.deepEqual(
      filterSkillCatalog(candidates, { ...DEFAULT_SKILL_CATALOG_FILTERS, query: `  ${query} ` }),
      [candidates.find((candidate) => candidate.id === expectedId)]
    );
  }
});

test('Skill 目录支持分类和风险筛选，并优先排列常用 Skill', () => {
  const candidates = [
    skill({ id: 'b', name: '乙', categories: ['a-category'], popular: false }),
    skill({
      id: 'c',
      name: '丙',
      categories: ['b-category'],
      popular: true,
      risk: {
        level: 'read_only',
        requires_confirmation: false,
        requires_approval: false,
        modifies_uploaded_files: false
      }
    }),
    skill({ id: 'a', name: '甲', categories: ['a-category'], popular: true })
  ];

  assert.deepEqual(
    sortSkillCatalog(candidates).map((candidate) => candidate.id),
    ['a', 'c', 'b']
  );
  assert.deepEqual(
    filterSkillCatalog(candidates, {
      ...DEFAULT_SKILL_CATALOG_FILTERS,
      category: 'a-category',
      risk: 'write'
    }).map((candidate) => candidate.id),
    ['a', 'b']
  );
});

test('清除筛选会恢复默认状态', () => {
  const filters = {
    ...DEFAULT_SKILL_CATALOG_FILTERS,
    query: '应收',
    category: '应收',
    risk: 'write' as const,
    popularOnly: true,
    dedicationUserId: 'user-1'
  };
  assert.equal(hasSkillCatalogFilters(filters), true);
  assert.deepEqual(clearSkillCatalogFilters(), DEFAULT_SKILL_CATALOG_FILTERS);
  assert.equal(hasSkillCatalogFilters(clearSkillCatalogFilters()), false);
});

test('目录卡片入口区分普通、工作流、辅助和未配置 Skill', () => {
  assert.deepEqual(skillCatalogActionFor(skill({ id: 'reconcile-bank' })), {
    kind: 'run',
    href: '/dashboard/skills/reconcile-bank/run',
    label: '开始核销'
  });
  assert.deepEqual(
    skillCatalogActionFor(skill({ id: 'ar-hexiao-daily', execution_mode: 'guided_workflow' })),
    {
      kind: 'workflow',
      href: '/dashboard/workflows?skill=ar-hexiao-daily',
      label: '开始核销'
    }
  );
  assert.deepEqual(
    skillCatalogActionFor(skill({ id: 'task-clarifier', action_label: '打开对话' })),
    {
      kind: 'supporting',
      href: '/dashboard/ai-chat',
      label: '打开对话'
    }
  );
  assert.deepEqual(skillCatalogActionFor(skill({ id: 'not-registered' })), {
    kind: 'unavailable',
    href: null,
    label: '暂不可运行'
  });
});

test('风险标签使用员工可理解的文字', () => {
  assert.deepEqual(
    skillRiskLabels(
      skill({
        risk: {
          level: 'external_action',
          requires_confirmation: true,
          requires_approval: true,
          modifies_uploaded_files: false
        }
      })
    ),
    ['外部操作', '需要确认', '需要审批']
  );
});

test('普通用户没有管理员专属配置时不生成专属人员筛选项', () => {
  assert.deepEqual(skillCatalogDedicationOptions(), []);
});
