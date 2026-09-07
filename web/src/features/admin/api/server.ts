import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  AdminUser,
  AuditEvent,
  AuditEventPage,
  PlatformSession,
  SkillPermission
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const USERNAME = /^[A-Za-z0-9_.-]+$/;

function objectBody(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '请求内容格式无效。');
  }
  return value as Record<string, unknown>;
}

function checkedUserId(value: string): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, '用户标识格式无效。');
  return value;
}

async function requirePlatformAdmin(): Promise<PlatformSession> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    throw new PlatformApiError(403, '只有平台管理员可以执行此操作。');
  }
  return session;
}

export async function listAdminUsers(): Promise<AdminUser[]> {
  await requirePlatformAdmin();
  return platformServerRequest<AdminUser[]>('/api/admin/users');
}

export async function createAdminUser(value: unknown): Promise<AdminUser> {
  const session = await requirePlatformAdmin();
  const body = objectBody(value);
  const username = typeof body.username === 'string' ? body.username.trim() : '';
  const displayName = typeof body.display_name === 'string' ? body.display_name.trim() : '';
  const password = typeof body.initial_password === 'string' ? body.initial_password : '';
  const role = body.role === 'skill_admin' ? 'skill_admin' : 'finance_user';
  if (!USERNAME.test(username) || username.length > 128) {
    throw new PlatformApiError(400, '用户名只能包含字母、数字、点、下划线和短横线。');
  }
  if (!displayName || displayName.length > 128) {
    throw new PlatformApiError(400, '显示名称必须为 1 到 128 个字符。');
  }
  if (password.length < 8 || password.length > 256) {
    throw new PlatformApiError(400, '初始密码必须为 8 到 256 个字符。');
  }
  return platformServerRequest<AdminUser>('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify({
      username,
      display_name: displayName,
      initial_password: password,
      role,
      department_id: session.department_id
    })
  });
}

export async function updateAdminUser(userId: string, value: unknown): Promise<AdminUser> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const allowed = new Set([
    'display_name',
    'role',
    'status',
    'clerk_user_id',
    'clerk_organization_id'
  ]);
  if (Object.keys(body).some((key) => !allowed.has(key))) {
    throw new PlatformApiError(400, '用户更新包含不支持的字段。');
  }
  return platformServerRequest<AdminUser>(`/api/admin/users/${checkedUserId(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body)
  });
}

export async function deleteAdminUser(userId: string): Promise<void> {
  await requirePlatformAdmin();
  await platformServerRequest<void>(`/api/admin/users/${checkedUserId(userId)}`, {
    method: 'DELETE'
  });
}

export async function resetAdminUserPassword(userId: string, value: unknown): Promise<AdminUser> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  const password = typeof body.initial_password === 'string' ? body.initial_password : '';
  if (password.length < 8 || password.length > 256) {
    throw new PlatformApiError(400, '一次性密码必须为 8 到 256 个字符。');
  }
  return platformServerRequest<AdminUser>(
    `/api/admin/users/${checkedUserId(userId)}/reset-password`,
    { method: 'POST', body: JSON.stringify({ initial_password: password }) }
  );
}

export async function replaceAdminUserPermissions(
  userId: string,
  value: unknown
): Promise<SkillPermission[]> {
  await requirePlatformAdmin();
  const body = objectBody(value);
  if (!Array.isArray(body.permissions) || body.permissions.length > 200) {
    throw new PlatformApiError(400, 'Skill 权限列表格式无效。');
  }
  const permissions = body.permissions.map((raw) => {
    const item = objectBody(raw);
    const skillId = typeof item.skill_id === 'string' ? item.skill_id : '';
    if (!skillId || skillId.length > 128) {
      throw new PlatformApiError(400, 'Skill 标识格式无效。');
    }
    return {
      skill_id: skillId,
      can_run: item.can_run === true,
      can_upload: item.can_upload === true,
      can_create_draft: item.can_create_draft === true,
      requires_approval: item.requires_approval === true
    };
  });
  if (new Set(permissions.map((item) => item.skill_id)).size !== permissions.length) {
    throw new PlatformApiError(400, '同一 Skill 不能重复授权。');
  }
  return platformServerRequest<SkillPermission[]>(
    `/api/admin/users/${checkedUserId(userId)}/skill-permissions`,
    { method: 'PUT', body: JSON.stringify({ permissions }) }
  );
}

export async function listAdminAuditEvents(
  action = '',
  actorId = '',
  limit = 100
): Promise<AuditEvent[]> {
  await requirePlatformAdmin();
  if (action.length > 128 || actorId.length > 128) {
    throw new PlatformApiError(400, '审计筛选条件过长。');
  }
  const params = new URLSearchParams({ limit: String(Math.min(Math.max(limit, 1), 500)) });
  if (action) params.set('action', action);
  if (actorId) params.set('actor_id', actorId);
  return platformServerRequest<AuditEvent[]>(`/api/admin/audit-events?${params}`);
}

export interface AdminAuditEventPageOptions {
  action?: string;
  actorId?: string;
  resourceType?: string;
  resourceId?: string;
  createdFrom?: string;
  createdTo?: string;
  limit?: number;
  beforeId?: number;
}

export async function listAdminAuditEventPage({
  action = '',
  actorId = '',
  resourceType = '',
  resourceId = '',
  createdFrom = '',
  createdTo = '',
  limit = 20,
  beforeId
}: AdminAuditEventPageOptions = {}): Promise<AuditEventPage> {
  await requirePlatformAdmin();
  const params = new URLSearchParams({
    limit: String(Math.min(Math.max(Math.trunc(limit), 1), 100))
  });
  if (action) params.set('action', action.slice(0, 128));
  if (actorId) params.set('actor_id', actorId.slice(0, 128));
  if (resourceType) params.set('resource_type', resourceType.slice(0, 64));
  if (resourceId) params.set('resource_id', resourceId.slice(0, 128));
  if (createdFrom) params.set('created_from', createdFrom);
  if (createdTo) params.set('created_to', createdTo);
  if (beforeId && Number.isSafeInteger(beforeId) && beforeId > 0) {
    params.set('before_id', String(beforeId));
  }
  return platformServerRequest<AuditEventPage>(`/api/admin/audit-events/page?${params}`);
}
