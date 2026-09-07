export const AR_LAB_SKILL_ID = 'ar-hexiao-daily-lab';

export function isArSkill(skillId: string | undefined): boolean {
  return skillId === 'ar-hexiao-daily' || skillId === AR_LAB_SKILL_ID;
}
