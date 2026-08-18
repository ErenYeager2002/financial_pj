export type SkillDetailEntry = 'standard' | 'workflow';

export function detailEntryForSkill(skill: { execution_mode?: string }): SkillDetailEntry {
  return skill.execution_mode === 'guided_workflow' ? 'workflow' : 'standard';
}
