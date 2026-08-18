import assert from 'node:assert/strict';
import test from 'node:test';

import { detailEntryForSkill } from '../src/features/skills/detail-entry.ts';

test('工作流型 Skill 详情页必须进入工作流 Agent', () => {
  assert.equal(detailEntryForSkill({ execution_mode: 'guided_workflow' }), 'workflow');
});

test('标准 Skill 详情页继续进入标准任务向导', () => {
  assert.equal(detailEntryForSkill({ execution_mode: 'standard' }), 'standard');
});
