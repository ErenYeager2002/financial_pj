export const PILOT_SKILL_ID = 'receivables-merge-and-split';
export function checkedSkillScope(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value === 'string' && /^native--[a-z][a-z0-9-]{0,71}$/.test(value)) return value;
  if (typeof value !== 'string' || value.length > 80 || !/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(value)) throw new Error('Skill 编号格式无效。');
  // Eligibility is checked against the authorized published manifest by the backend.
  return value;
}
export function skillSessionPrefix(skillId?: string): string {
  return skillId ? `skill-${skillId}__` : '';
}
export function belongsToSkillSession(sessionId: string, skillId?: string): boolean {
  if (!skillId) return !sessionId.startsWith('skill-');
  if (sessionId.startsWith(skillSessionPrefix(skillId))) return true;
  // Preserve the original pilot's UUID sessions without prefix collisions.
  return skillId === PILOT_SKILL_ID && /^skill-receivables-merge-and-split-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId);
}
