import assert from 'node:assert/strict';
import test from 'node:test';
import { checkedSkillScope, belongsToSkillSession, skillSessionPrefix, PILOT_SKILL_ID } from '../src/features/ai-chat/skill-chat-scope.ts';
test('scope syntax is generic; backend owns eligibility', () => {
 assert.equal(checkedSkillScope(PILOT_SKILL_ID), PILOT_SKILL_ID);
 assert.equal(checkedSkillScope(undefined), undefined);
 assert.equal(checkedSkillScope('custom-skill'), 'custom-skill');
 assert.throws(() => checkedSkillScope('../secret'));
});
test('general and tool conversations cannot be mixed', () => {
 const scoped = skillSessionPrefix(PILOT_SKILL_ID) + 'example';
 assert.equal(belongsToSkillSession(scoped, PILOT_SKILL_ID), true);
 assert.equal(belongsToSkillSession(scoped), false);
 assert.equal(belongsToSkillSession('general-id', PILOT_SKILL_ID), false);
 assert.equal(belongsToSkillSession('general-id'), true);
});

test('similar skill ids cannot share sessions', () => {
 assert.equal(belongsToSkillSession(skillSessionPrefix('sales-extra') + 'id', 'sales'), false);
 assert.equal(belongsToSkillSession('skill-receivables-merge-and-split-12345678-1234-1234-1234-123456789012', PILOT_SKILL_ID), true);
});

test('generated session id satisfies persistence contract', () => {
 assert.match(skillSessionPrefix('sales-extra') + '12345678-1234-1234-1234-123456789012', /^[A-Za-z0-9_-]{1,128}$/);
});
