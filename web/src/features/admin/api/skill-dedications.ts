import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import {
  platformServerRequest,
  platformServerResponse
} from '@/features/platform-api/server-client';
import type {
  PlatformSession,
  SkillDedication,
  SkillDedicationWrite
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SKILL_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

function checkedSkillId(value: string): string {
  if (!SKILL_ID.test(value)) throw new PlatformApiError(400, 'Skill 标识格式无效。');
  return value;
}

function checkedUserId(value: string): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, '用户标识格式无效。');
  return value;
}

async function requirePlatformAdmin(): Promise<void> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    throw new PlatformApiError(403, '只有平台管理员可以管理 Skill 专属员工。');
  }
}

export async function listSkillDedications(): Promise<SkillDedication[]> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillDedication[]>('/api/admin/skill-dedications');
}

export async function setSkillDedication(
  skillId: string,
  userId: string
): Promise<SkillDedication> {
  await requirePlatformAdmin();
  const payload: SkillDedicationWrite = { user_id: checkedUserId(userId) };
  return platformServerRequest<SkillDedication>(
    `/api/admin/skill-dedications/${encodeURIComponent(checkedSkillId(skillId))}`,
    { method: 'PUT', body: JSON.stringify(payload) }
  );
}

export async function clearSkillDedication(skillId: string): Promise<void> {
  await requirePlatformAdmin();
  const response = await platformServerResponse(
    `/api/admin/skill-dedications/${encodeURIComponent(checkedSkillId(skillId))}`,
    { method: 'DELETE' }
  );
  await response.body?.cancel();
}
