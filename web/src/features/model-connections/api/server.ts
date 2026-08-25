import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  ModelConnection,
  ModelProvider,
  PlatformSession
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function requireAdmin(): Promise<void> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    throw new PlatformApiError(403, '只有管理员可以管理模型连接。');
  }
}

function objectBody(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '请求内容格式无效。');
  }
  return value as Record<string, unknown>;
}

function checkedConnectionId(value: string): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, '模型连接标识格式无效。');
  return value;
}

export async function listAdminModelConnections(): Promise<ModelConnection[]> {
  await requireAdmin();
  return platformServerRequest<ModelConnection[]>('/api/model-connections');
}

export async function listAdminModelProviders(): Promise<ModelProvider[]> {
  await requireAdmin();
  return platformServerRequest<ModelProvider[]>('/api/model-providers');
}

export async function createAdminModelConnection(value: unknown): Promise<ModelConnection> {
  await requireAdmin();
  const body = objectBody(value);
  const providerId = typeof body.provider_id === 'string' ? body.provider_id.trim() : '';
  const apiKey = typeof body.api_key === 'string' ? body.api_key.trim() : '';
  const baseUrl = typeof body.base_url === 'string' ? body.base_url.trim() : '';
  const model = typeof body.model === 'string' ? body.model.trim() : '';
  if (!providerId || providerId.length > 64) {
    throw new PlatformApiError(400, '请选择模型供应商。');
  }
  if (apiKey.length < 8 || apiKey.length > 512) {
    throw new PlatformApiError(400, 'API Key 长度必须为 8 到 512 个字符。');
  }
  if (baseUrl.length > 512 || model.length > 255) {
    throw new PlatformApiError(400, '模型服务地址或模型名称过长。');
  }
  return platformServerRequest<ModelConnection>('/api/model-connections', {
    method: 'POST',
    body: JSON.stringify({
      provider_id: providerId,
      api_key: apiKey,
      base_url: baseUrl || null,
      model: model || null
    })
  });
}

export async function updateAdminModelConnection(
  connectionId: string,
  value: unknown
): Promise<ModelConnection> {
  await requireAdmin();
  const body = objectBody(value);
  const selectedModel = typeof body.selected_model === 'string' ? body.selected_model.trim() : '';
  if (!selectedModel || selectedModel.length > 255) {
    throw new PlatformApiError(400, '请选择有效的模型。');
  }
  return platformServerRequest<ModelConnection>(
    `/api/model-connections/${checkedConnectionId(connectionId)}`,
    { method: 'PATCH', body: JSON.stringify({ selected_model: selectedModel }) }
  );
}

export async function refreshAdminModelConnection(connectionId: string): Promise<ModelConnection> {
  await requireAdmin();
  return platformServerRequest<ModelConnection>(
    `/api/model-connections/${checkedConnectionId(connectionId)}/refresh`,
    { method: 'POST' }
  );
}

export async function deleteAdminModelConnection(connectionId: string): Promise<null> {
  await requireAdmin();
  return platformServerRequest<null>(
    `/api/model-connections/${checkedConnectionId(connectionId)}`,
    { method: 'DELETE' }
  );
}
