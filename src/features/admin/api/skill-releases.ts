import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  PlatformSession,
  SkillRelease,
  SkillReleaseInboxItem,
  SkillReleaseMetadataUpdate
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PACKAGE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$/;

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
