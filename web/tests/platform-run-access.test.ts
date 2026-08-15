import assert from 'node:assert/strict';
import test from 'node:test';

// @ts-expect-error Node's built-in TypeScript runner requires the explicit extension.
import { isRunnableSkill } from '../src/features/run-setup/run-eligibility.ts';

function skill(overrides: Record<string, unknown> = {}) {
  return {
    id: 'any-published-skill',
    status: 'published',
    execution_mode: 'standard',
    risk: { level: 'read_only', modifies_uploaded_files: false },
    ...overrides
  };
}

test('所有后端已授权的安全标准 Skill 都可以进入任务向导', () => {
  assert.equal(isRunnableSkill(skill()), true);
  assert.equal(isRunnableSkill(skill({ id: 'newly-published-skill' })), true);
});

test('未发布、工作流或写入型 Skill 仍不能从标准任务向导执行', () => {
  assert.equal(isRunnableSkill(skill({ status: 'draft' })), false);
  assert.equal(isRunnableSkill(skill({ execution_mode: 'workflow' })), false);
  assert.equal(
    isRunnableSkill(skill({ risk: { level: 'write', modifies_uploaded_files: true } })),
    false
  );
});
