import assert from 'node:assert/strict';
import test from 'node:test';

import {
  executionExperienceForSkill,
  registeredBusinessSkillIds
} from '../src/features/skills/execution-experience.ts';

const publishedBusinessSkills = [
  'ar-hexiao-daily',
  'reconcile-bank',
  'receivables-merge',
  'split-by-sales',
  'labor-invoice-check',
  'withholding-report-rename',
  'compliance-spot-check',
  'dreame-ar-progress-diff',
  'dept-expense-alloc',
  'order-daily-summary',
  'project-detail-to-ledger'
];

test('所有已发布业务 Skill 都有受控执行体验', () => {
  assert.deepEqual(registeredBusinessSkillIds().toSorted(), publishedBusinessSkills.toSorted());
  for (const skillId of publishedBusinessSkills) {
    const experience = executionExperienceForSkill(skillId);
    assert.ok(experience);
    assert.equal(experience.classification, 'business');
    assert.ok(experience.reviewItems.length > 0);
    assert.ok(experience.workerChecks.length > 0);
    assert.ok(experience.resultHighlights.length > 0);
  }
});

test('基础和辅助 Skill 不会被当作业务 Skill', () => {
  assert.equal(executionExperienceForSkill('xlsx')?.classification, 'foundation');
  assert.equal(executionExperienceForSkill('env-doctor')?.classification, 'supporting');
  assert.equal(executionExperienceForSkill('task-clarifier')?.family, 'conversation');
});

test('未知 Skill 不会获得通用执行体验', () => {
  assert.equal(executionExperienceForSkill('not-registered'), null);
});
