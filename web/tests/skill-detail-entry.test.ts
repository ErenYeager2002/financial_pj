import assert from 'node:assert/strict';
import test from 'node:test';

import { detailEntryForSkill } from '../src/features/skills/detail-entry.ts';

test('工作流型 Skill 详情页必须进入工作流 Agent', () => {
  assert.equal(
    detailEntryForSkill({ id: 'ar-hexiao-daily', execution_mode: 'guided_workflow' }),
    'workflow'
  );
});

test('基础文件 Skill 才能进入通用文件处理体验', () => {
  assert.equal(detailEntryForSkill({ id: 'xlsx', execution_mode: 'standard' }), 'foundation');
});

test('已登记业务 Skill 进入专属执行体验', () => {
  assert.equal(
    detailEntryForSkill({ id: 'reconcile-bank', execution_mode: 'standard' }),
    'business'
  );
});

test('未登记业务 Skill 被阻止而不是回退到通用表单', () => {
  assert.equal(detailEntryForSkill({ id: 'unknown-business-skill' }), 'blocked');
});
