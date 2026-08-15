import type {
  RunRecord,
  ModelConnection,
  ModelProviderInfo,
  SkillManifest,
  ServiceCredential,
  UploadedFile,
  UserSession,
  WorkflowRecord,
  WorkflowBatchRecord,
  AdminUser,
  SkillPermission,
} from './types'

export async function request<T>(
  path: string,
  init: RequestInit = {},
  options: { redirectOnUnauthorized?: boolean } = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: {
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init.headers || {}),
    },
  })
  if (response.status === 401 && options.redirectOnUnauthorized !== false) {
    if (window.location.pathname !== '/login') {
      window.location.assign('/login')
    }
    throw new Error('未登录或会话已失效')
  }
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
  login: (username: string, password: string) =>
    request<UserSession>(
      '/api/auth/login',
      {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      },
      { redirectOnUnauthorized: false },
    ),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<UserSession>(
      '/api/auth/change-password',
      {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      },
      { redirectOnUnauthorized: false },
    ),
  health: () => request<import('./types').PlatformHealth>('/api/health'),
  skills: () => request<SkillManifest[]>('/api/skills'),
  skill: (id: string) => request<SkillManifest>(`/api/skills/${id}`),
  runs: () => request<RunRecord[]>('/api/runs'),
  run: (id: string) => request<RunRecord>(`/api/runs/${id}`),
  modelConnections: () => request<ModelConnection[]>('/api/model-connections'),
  modelProviders: () => request<ModelProviderInfo[]>('/api/model-providers'),
  connectModel: (
    providerId: string,
    apiKey: string,
    baseUrl?: string,
    model?: string,
  ) =>
    request<ModelConnection>('/api/model-connections', {
      method: 'POST',
      body: JSON.stringify({
        provider_id: providerId,
        api_key: apiKey,
        base_url: baseUrl || null,
        model: model || null,
      }),
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
  serviceCredential: (service: string) =>
    request<ServiceCredential>(`/api/service-credentials/${service}`),
  saveServiceCredential: (service: string, account: string, password: string) =>
    request<ServiceCredential>(`/api/service-credentials/${service}`, {
      method: 'PUT',
      body: JSON.stringify({ account, password }),
    }),
  deleteServiceCredential: (service: string) =>
    request<void>(`/api/service-credentials/${service}`, { method: 'DELETE' }),
  upload: async (role: string, file: File) => {
    const data = new FormData()
    data.append('role', role)
    data.append('upload', file)
    return request<UploadedFile>('/api/files', { method: 'POST', body: data })
  },
  deleteFile: (fileId: string) =>
    request<void>(`/api/files/${fileId}`, { method: 'DELETE' }),
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
  createWorkflow: (skillId: string, modelConnectionId: string, model?: string) =>
    request<WorkflowRecord>('/api/workflows', {
      method: 'POST',
      body: JSON.stringify({
        skill_id: skillId,
        model_connection_id: modelConnectionId,
        model: model || null,
      }),
    }),
  startWorkflow: (
    skillId: string,
    reconciliationDate: string,
    files: Record<string, string[]>,
    modelConnectionId: string,
    model?: string,
  ) =>
    request<WorkflowRecord>('/api/workflows/start', {
      method: 'POST',
      body: JSON.stringify({
        skill_id: skillId,
        reconciliation_date: reconciliationDate,
        files,
        model_connection_id: modelConnectionId,
        model: model || null,
      }),
    }),
  startWorkflowBatch: (
    skillId: string,
    reconciliationDates: string[],
    files: Record<string, string[]>,
    modelConnectionId: string,
    model?: string,
  ) =>
    request<WorkflowBatchRecord>('/api/workflow-batches/start', {
      method: 'POST',
      body: JSON.stringify({
        skill_id: skillId,
        reconciliation_dates: reconciliationDates,
        files,
        model_connection_id: modelConnectionId,
        model: model || null,
      }),
    }),
  workflowBatches: () => request<WorkflowBatchRecord[]>('/api/workflow-batches'),
  workflowBatch: (id: string) => request<WorkflowBatchRecord>(`/api/workflow-batches/${id}`),
  retryWorkflowBatch: (id: string) =>
    request<WorkflowBatchRecord>(`/api/workflow-batches/${id}/retry`, { method: 'POST' }),
  workflows: () => request<WorkflowRecord[]>('/api/workflows'),
  workflow: (id: string) => request<WorkflowRecord>(`/api/workflows/${id}`),
  updateWorkflowFiles: (id: string, files: Record<string, string[]>) =>
    request<WorkflowRecord>(`/api/workflows/${id}/files`, {
      method: 'PUT',
      body: JSON.stringify({ files }),
    }),
  sendWorkflowMessage: (id: string, content: string) =>
    request<WorkflowRecord>(`/api/workflows/${id}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),
  confirmWorkflow: (id: string) =>
    request<WorkflowRecord>(`/api/workflows/${id}/confirm`, { method: 'POST' }),
  rebuildWorkflow: (id: string) =>
    request<WorkflowRecord>(`/api/workflows/${id}/rebuild`, { method: 'POST' }),
  resetWorkflow: (id: string) =>
    request<WorkflowRecord>(`/api/workflows/${id}/reset`, {
      method: 'POST',
    }),
  reloadRegistry: () =>
    request<{ skills: number; errors: Array<{ path: string; error: string }> }>(
      '/api/admin/registry/reload',
      { method: 'POST' },
    ),
  adminUsers: () => request<AdminUser[]>('/api/admin/users'),
  createAdminUser: (body: {
    username: string
    display_name: string
    initial_password: string
    role: 'finance_user' | 'skill_admin'
    department_id: string
  }) =>
    request<AdminUser>('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateAdminUser: (
    userId: string,
    body: Partial<Pick<AdminUser, 'display_name' | 'role' | 'status'>>,
  ) =>
    request<AdminUser>(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  replaceSkillPermissions: (userId: string, permissions: SkillPermission[]) =>
    request<SkillPermission[]>(`/api/admin/users/${userId}/skill-permissions`, {
      method: 'PUT',
      body: JSON.stringify({ permissions }),
    }),
}

export function eventStreamUrl(runId: string, after = 0): string {
  // SSE 身份来自会话 Cookie，URL 不再携带用户身份参数。
  const query = new URLSearchParams({ after: String(after) })
  return `/api/runs/${runId}/events?${query.toString()}`
}
