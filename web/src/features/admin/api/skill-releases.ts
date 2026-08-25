import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  PlatformSession,
  SkillAvailability,
  SkillRelease,
  SkillReleaseInboxItem,
  SkillReleaseMetadataUpdate,
  SkillRollout,
  SkillSourceBinding,
  SkillSourceDiscovery,
  SkillSourceUpdateCheck
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PACKAGE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$/;
const SKILL_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const SEMVER = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
export const FINANCE_SKILLS_REPOSITORY = 'https://gitee.com/Lee157/finance-skills.git';

function objectBody(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '请求内容格式无效。');
  }
  return value as Record<string, unknown>;
}

function checkedReleaseId(value: string): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, '发布记录标识格式无效。');
  return value;
}

function checkedSkillId(value: string): string {
  if (!SKILL_ID.test(value)) throw new PlatformApiError(400, 'Skill 标识格式无效。');
  return value;
}

async function requirePlatformAdmin(): Promise<void> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    throw new PlatformApiError(403, '只有平台管理员可以管理 Skill 发布。');
  }
}

export async function listSkillReleases(): Promise<SkillRelease[]> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillRelease[]>('/api/admin/skill-releases');
}

export async function listSkillReleaseInbox(): Promise<SkillReleaseInboxItem[]> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillReleaseInboxItem[]>('/api/admin/skill-releases/inbox');
}

export async function importSkillRelease(value: unknown): Promise<SkillRelease> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const packageName = typeof body.package_name === 'string' ? body.package_name : '';
  if (!PACKAGE.test(packageName) || packageName.length > 255) {
    throw new PlatformApiError(400, '发布包名称无效。');
  }
  return platformServerRequest<SkillRelease>('/api/admin/skill-releases/import', {
    method: 'POST',
    body: JSON.stringify({ package_name: packageName })
  });
}

export async function updateSkillReleaseMetadata(
  releaseId: string,
  value: unknown
): Promise<SkillRelease> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const allowed = new Set([
    'name',
    'description',
    'category',
    'tags',
    'ui',
    'progress_stages',
    'result_presentation'
  ]);
  if (Object.keys(body).some((key) => !allowed.has(key))) {
    throw new PlatformApiError(400, '元数据更新包含不支持的字段。');
  }
  if (JSON.stringify(body).length > 20_000) {
    throw new PlatformApiError(413, '元数据内容超过限制。');
  }
  return platformServerRequest<SkillRelease>(
    `/api/admin/skill-releases/${checkedReleaseId(releaseId)}`,
    { method: 'PATCH', body: JSON.stringify(body as SkillReleaseMetadataUpdate) }
  );
}

export async function reviewSkillRelease(releaseId: string, value: unknown): Promise<SkillRelease> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const decision = body.decision === 'reject' ? 'reject' : 'approve';
  const notes = typeof body.notes === 'string' ? body.notes.trim() : '';
  if (notes.length < 2 || notes.length > 2000) {
    throw new PlatformApiError(400, '审核意见必须为 2 到 2000 个字符。');
  }
  return platformServerRequest<SkillRelease>(
    `/api/admin/skill-releases/${checkedReleaseId(releaseId)}/review`,
    { method: 'POST', body: JSON.stringify({ decision, notes }) }
  );
}

export async function publishSkillRelease(
  releaseId: string,
  value: unknown
): Promise<SkillRelease> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const confirmation = typeof body.confirmation === 'string' ? body.confirmation : '';
  if (confirmation.length < 4 || confirmation.length > 255) {
    throw new PlatformApiError(400, '确认文字格式无效。');
  }
  return platformServerRequest<SkillRelease>(
    `/api/admin/skill-releases/${checkedReleaseId(releaseId)}/publish`,
    { method: 'POST', body: JSON.stringify({ confirmation }) }
  );
}

export async function listSkillSourceBindings(): Promise<SkillSourceBinding[]> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillSourceBinding[]>('/api/admin/skill-sources/bindings');
}

export async function discoverSkillSources(): Promise<SkillSourceDiscovery> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillSourceDiscovery>('/api/admin/skill-sources/discover', {
    method: 'POST',
    body: JSON.stringify({ repository_url: FINANCE_SKILLS_REPOSITORY, tracking_ref: 'main' })
  });
}

export async function confirmSkillSourceBinding(value: unknown): Promise<SkillSourceBinding> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const skillId = checkedSkillId(typeof body.skill_id === 'string' ? body.skill_id : '');
  const sourcePath = typeof body.source_path === 'string' ? body.source_path : '';
  const expectedCommit = typeof body.expected_commit === 'string' ? body.expected_commit : '';
  if (sourcePath !== `skills/${skillId}` || !/^[0-9a-f]{40}$/.test(expectedCommit)) {
    throw new PlatformApiError(400, '源码绑定信息无效。');
  }
  return platformServerRequest<SkillSourceBinding>('/api/admin/skill-sources/bindings', {
    method: 'POST',
    body: JSON.stringify({
      skill_id: skillId,
      repository_url: FINANCE_SKILLS_REPOSITORY,
      tracking_ref: 'main',
      source_path: sourcePath,
      expected_commit: expectedCommit
    })
  });
}

export async function checkSkillSourceUpdate(skillId: string): Promise<SkillSourceUpdateCheck> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillSourceUpdateCheck>(
    `/api/admin/skill-sources/bindings/${checkedSkillId(skillId)}/check-update`,
    { method: 'POST' }
  );
}

export async function prepareSkillSourceRelease(
  skillId: string,
  value: unknown
): Promise<SkillRelease> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const version = typeof body.version === 'string' ? body.version.trim() : '';
  if (!SEMVER.test(version)) throw new PlatformApiError(400, '版本号必须使用 SemVer。');
  return platformServerRequest<SkillRelease>(
    `/api/admin/skill-sources/bindings/${checkedSkillId(skillId)}/prepare-release`,
    { method: 'POST', body: JSON.stringify({ version }) }
  );
}

export async function updateDisabledSkill(skillId: string): Promise<SkillRelease> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillRelease>(
    `/api/admin/skills/${checkedSkillId(skillId)}/update`,
    { method: 'POST' }
  );
}

export async function startSkillRollout(releaseId: string, value: unknown): Promise<SkillRollout> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const confirmation = typeof body.confirmation === 'string' ? body.confirmation : '';
  if (confirmation.length < 8 || confirmation.length > 255) {
    throw new PlatformApiError(400, '确认文字格式无效。');
  }
  return platformServerRequest<SkillRollout>(
    `/api/admin/skill-releases/${checkedReleaseId(releaseId)}/rollout`,
    { method: 'POST', body: JSON.stringify({ confirmation }) }
  );
}

export async function getSkillRollout(rolloutId: string): Promise<SkillRollout> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillRollout>(
    `/api/admin/skill-rollouts/${checkedReleaseId(rolloutId)}`
  );
}

export async function getSkillAvailability(skillId: string): Promise<SkillAvailability> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillAvailability>(
    `/api/admin/skills/${checkedSkillId(skillId)}/availability`
  );
}

export async function listSkillAvailability(): Promise<SkillAvailability[]> {
  await requirePlatformAdmin();
  return platformServerRequest<SkillAvailability[]>('/api/admin/skills/availability');
}

export async function transitionSkillAvailability(
  skillId: string,
  value: unknown
): Promise<SkillAvailability> {
  await requirePlatformAdmin();
  const checkedId = checkedSkillId(skillId);
  const body = objectBody(value);
  const targetState = String(body.target_state ?? '');
  if (!['enabled', 'draining', 'disabled'].includes(targetState)) {
    throw new PlatformApiError(400, 'Skill 可用状态目标无效。');
  }
  const confirmation = typeof body.confirmation === 'string' ? body.confirmation : '';
  const expected = targetState === 'enabled' ? `启用 ${checkedId}` : `禁用 ${checkedId}`;
  if (confirmation !== expected) {
    throw new PlatformApiError(422, `确认文字必须为：${expected}`);
  }
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (reason.length < 2 || reason.length > 500) {
    throw new PlatformApiError(400, '状态变更原因必须为 2 到 500 个字符。');
  }
  return platformServerRequest<SkillAvailability>(`/api/admin/skills/${checkedId}/availability`, {
    method: 'POST',
    body: JSON.stringify({ target_state: targetState, reason })
  });
}
