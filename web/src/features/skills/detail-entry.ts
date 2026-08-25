import { executionExperienceForSkill } from './execution-experience.ts';

export type SkillDetailEntry = 'foundation' | 'supporting' | 'business' | 'workflow' | 'blocked';

export function detailEntryForSkill(skill: {
  id?: string;
  execution_mode?: string;
}): SkillDetailEntry {
  if (!skill.id) return 'blocked';
  const experience = executionExperienceForSkill(skill.id);
  if (!experience) return 'blocked';
  if (experience.family === 'workflow') return 'workflow';
  return experience.classification;
}
