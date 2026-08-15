import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  AdminAssistantProfile,
  AssistantStatus,
  ModelConnection,
  PlatformSession,
  RunDetail,
  TaskDraft
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function checkedUuid(value: string, label = '标识'): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, `${label}格式无效。`);
  return value;
}

function objectBody(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '请求内容格式无效。');
  }
  return value as Record<string, unknown>;
}

async function requireAdmin(): Promise<void> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    throw new PlatformApiError(403, '只有管理员可以配置 AI 助手。');
  }
}

export function getAssistantStatus(): Promise<AssistantStatus> {
  return platformServerRequest<AssistantStatus>('/api/assistant/status');
}

export function prepareAssistantDraft(value: unknown): Promise<TaskDraft> {
  const body = objectBody(value);
  const message = typeof body.message === 'string' ? body.message.trim() : '';
  const fileIds = Array.isArray(body.file_ids) ? body.file_ids : [];
  if (!message || message.length > 4000) {
    throw new PlatformApiError(400, '任务描述必须为 1 到 4000 个字符。');
  }
  if (fileIds.length > 20 || fileIds.some((item) => typeof item !== 'string' || !UUID.test(item))) {
    throw new PlatformApiError(400, '所选文件标识无效。');
  }
  return platformServerRequest<TaskDraft>('/api/assistant/prepare', {
    method: 'POST',
    body: JSON.stringify({ message, file_ids: fileIds })
  });
}

export function getTaskDraft(draftId: string): Promise<TaskDraft> {
  return platformServerRequest<TaskDraft>(`/api/task-drafts/${checkedUuid(draftId, '草稿标识')}`);
}

export function updateTaskDraft(draftId: string, value: unknown): Promise<TaskDraft> {
  const body = objectBody(value);
  const allowed = new Set(['parameters', 'files']);
  if (Object.keys(body).some((key) => !allowed.has(key))) {
    throw new PlatformApiError(400, '草稿更新包含不支持的字段。');
  }
  return platformServerRequest<TaskDraft>(`/api/task-drafts/${checkedUuid(draftId, '草稿标识')}`, {
    method: 'PATCH',
    body: JSON.stringify(body)
  });
}

export function confirmTaskDraft(draftId: string): Promise<RunDetail> {
  return platformServerRequest<RunDetail>(
    `/api/task-drafts/${checkedUuid(draftId, '草稿标识')}/confirm`,
    { method: 'POST' }
  );
}

export function deleteTaskDraft(draftId: string): Promise<null> {
  return platformServerRequest<null>(`/api/task-drafts/${checkedUuid(draftId, '草稿标识')}`, {
    method: 'DELETE'
  });
}

export async function getAdminAssistantProfile(): Promise<AdminAssistantProfile> {
  await requireAdmin();
  return platformServerRequest<AdminAssistantProfile>('/api/admin/assistant-profile');
}

export async function listAdminModelConnections(): Promise<ModelConnection[]> {
  await requireAdmin();
  return platformServerRequest<ModelConnection[]>('/api/model-connections');
}

export async function configureAdminAssistantProfile(
  value: unknown
): Promise<AdminAssistantProfile> {
  await requireAdmin();
  const body = objectBody(value);
  const connectionId = typeof body.connection_id === 'string' ? body.connection_id : '';
  const model = typeof body.model === 'string' ? body.model.trim() : '';
  if (!UUID.test(connectionId) || !model || model.length > 255) {
    throw new PlatformApiError(400, '模型连接或模型名称无效。');
  }
  return platformServerRequest<AdminAssistantProfile>('/api/admin/assistant-profile', {
    method: 'PUT',
    body: JSON.stringify({ connection_id: connectionId, model })
  });
}

export async function removeAdminAssistantProfile(): Promise<null> {
  await requireAdmin();
  return platformServerRequest<null>('/api/admin/assistant-profile', { method: 'DELETE' });
}
