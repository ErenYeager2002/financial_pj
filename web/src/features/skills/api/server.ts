import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { SkillDetail, SkillSummary } from '@/features/platform-api/types';

const SKILL_ID = /^[A-Za-z0-9._-]+$/;

function checkedSkillId(skillId: string): string {
  if (!SKILL_ID.test(skillId)) {
    throw new PlatformApiError(400, 'Skill 标识格式无效。');
  }
  return skillId;
}

export function listSkillCatalog(): Promise<SkillDetail[]> {
  return platformServerRequest<SkillDetail[]>('/api/catalog/skills');
}

export function listSkillSummaries(): Promise<SkillSummary[]> {
  return platformServerRequest<SkillSummary[]>('/api/catalog/skill-summaries');
}

export function getSkillCatalogItem(skillId: string): Promise<SkillDetail> {
  return platformServerRequest<SkillDetail>(`/api/catalog/skills/${checkedSkillId(skillId)}`);
}
