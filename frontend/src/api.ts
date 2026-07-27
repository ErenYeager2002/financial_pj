import type {
  RunRecord,
  ModelConnection,
  SkillManifest,
  UploadedFile,
  UserRole,
  UserSession,
} from './types'

const ROLE_KEY = 'financial-user-role'

export function getRole(): UserRole {
  return (localStorage.getItem(ROLE_KEY) as UserRole) || 'finance_user'
}

export function setRole(role: UserRole): void {
  localStorage.setItem(ROLE_KEY, role)
}

export function authHeaders(): Record<string, string> {
  const role = getRole()
  return {
    'X-User-Id': role === 'skill_admin' ? 'skill-admin' : 'demo-user',
    'X-User-Role': role,
    'X-Department-Id': 'finance',
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init.headers || {}),
    },
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      message =
        typeof body.detail === 'string'
          ? body.detail
          : body.detail?.message || JSON.stringify(body.detail)
    } catch {
      // 保留默认错误
    }
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  session: () => request<UserSession>('/api/session'),
  skills: () => request<SkillManifest[]>('/api/skills'),
  skill: (id: string) => request<SkillManifest>(`/api/skills/${id}`),
  runs: () => request<RunRecord[]>('/api/runs'),
  run: (id: string) => request<RunRecord>(`/api/runs/${id}`),
  modelConnections: () => request<ModelConnection[]>('/api/model-connections'),
  connectModel: (apiKey: string) =>
    request<ModelConnection>('/api/model-connections', {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey }),
    }),
  selectModel: (connectionId: string, selectedModel: string) =>
    request<ModelConnection>(`/api/model-connections/${connectionId}`, {
      method: 'PATCH',
      body: JSON.stringify({ selected_model: selectedModel }),
    }),
  refreshModel: (connectionId: string) =>
    request<ModelConnection>(`/api/model-connections/${connectionId}/refresh`, {
      method: 'POST',
    }),
  deleteModel: (connectionId: string) =>
    request<void>(`/api/model-connections/${connectionId}`, { method: 'DELETE' }),
  upload: async (role: string, file: File) => {
    const data = new FormData()
    data.append('role', role)
    data.append('upload', file)
    return request<UploadedFile>('/api/files', { method: 'POST', body: data })
  },
  interpret: (
    skillId: string,
    message: string,
    parameters: Record<string, unknown>,
    modelConnectionId?: string,
    model?: string,
  ) =>
    request<{
      parameters: Record<string, unknown>
      missing: string[]
      source: string
      notes: string[]
    }>(`/api/skills/${skillId}/interpret`, {
      method: 'POST',
      body: JSON.stringify({
        message,
        parameters,
        model_connection_id: modelConnectionId || null,
        model: model || null,
      }),
    }),
  createRun: (
    skillId: string,
    message: string,
    parameters: Record<string, unknown>,
    files: Record<string, string | string[]>,
    modelConnectionId?: string,
    model?: string,
  ) =>
    request<RunRecord>('/api/runs', {
      method: 'POST',
      body: JSON.stringify({
        skill_id: skillId,
        message,
        parameters,
        files,
        idempotency_key: crypto.randomUUID(),
        model_connection_id: modelConnectionId || null,
        model: model || null,
      }),
    }),
  confirmRun: (id: string) =>
    request<{ id: string; state: string; message: string }>(`/api/runs/${id}/confirm`, {
      method: 'POST',
    }),
  cancelRun: (id: string) =>
    request<{ id: string; state: string; message: string }>(`/api/runs/${id}/cancel`, {
      method: 'POST',
    }),
  reloadRegistry: () =>
    request<{ skills: number; errors: Array<{ path: string; error: string }> }>(
      '/api/admin/registry/reload',
      { method: 'POST' },
    ),
}

export function eventStreamUrl(runId: string, after = 0): string {
  const role = getRole()
  const userId = role === 'skill_admin' ? 'skill-admin' : 'demo-user'
  const query = new URLSearchParams({
    after: String(after),
    user_id: userId,
    role,
    department_id: 'finance',
  })
  return `/api/runs/${runId}/events?${query.toString()}`
}
