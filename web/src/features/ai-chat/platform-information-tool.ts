import type { AgentTool } from '@financial-platform/agent-runtime';
import { Type } from 'typebox';

type PlatformRole = 'finance_user' | 'skill_admin';

const ADMIN_RESOURCES = new Set<PlatformInformationResource>([
  'users',
  'audit_events',
  'approvals',
  'model_connections',
  'model_providers',
  'skill_releases',
  'skill_source_bindings',
  'skill_availability',
  'skill_dedications',
  'workflow_definitions',
  'observability'
]);

export type PlatformInformationResource =
  | 'overview'
  | 'skills'
  | 'skill_detail'
  | 'task_center'
  | 'files'
  | 'file_detail'
  | 'runs'
  | 'run_detail'
  | 'run_steps'
  | 'run_approvals'
  | 'run_events'
  | 'workflows'
  | 'workflow_detail'
  | 'workflow_fetched_data'
  | 'workflow_batches'
  | 'workflow_batch_detail'
  | 'workflow_batch_fetched_data'
  | 'task_reminders'
  | 'profile'
  | 'assistant_status'
  | 'users'
  | 'audit_events'
  | 'approvals'
  | 'model_connections'
  | 'model_providers'
  | 'skill_releases'
  | 'skill_source_bindings'
  | 'skill_availability'
  | 'skill_dedications'
  | 'workflow_definitions'
  | 'observability';

export interface PlatformInformationQuery {
  resource: PlatformInformationResource;
  id?: string;
  page?: number;
  cursor?: string;
  query?: string;
  state?: string;
  date?: string;
  issues_only?: boolean;
}

type PlatformRequester = (path: string) => Promise<unknown>;

const SENSITIVE_KEYS = new Set([
  'account',
  'actorid',
  'apikey',
  'apikeyhint',
  'authorization',
  'clerkorganizationid',
  'clerkuserid',
  'commit',
  'confirmedby',
  'cookie',
  'createdby',
  'credential',
  'departmentid',
  'downloadurl',
  'fileid',
  'fileids',
  'hash',
  'importedby',
  'localpath',
  'ownerid',
  'password',
  'publishedby',
  'repositoryurl',
  'resourceid',
  'reviewedby',
  'secret',
  'sessionid',
  'sha256',
  'sourcepath',
  'sourcerepository',
  'token',
  'updatedby',
  'workspace'
]);

function normalizedKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '');
}

function isSensitiveKey(key: string): boolean {
  const normalized = normalizedKey(key);
  return (
    SENSITIVE_KEYS.has(normalized) ||
    normalized.endsWith('apikey') ||
    normalized.endsWith('password') ||
    normalized.endsWith('secret') ||
    normalized.endsWith('token') ||
    normalized.endsWith('credential') ||
    normalized.endsWith('localpath') ||
    normalized.endsWith('sourcepath') ||
    normalized.endsWith('downloadurl') ||
    normalized.endsWith('repositoryurl') ||
    normalized.endsWith('sha256') ||
    normalized.endsWith('hash') ||
    normalized.endsWith('commit') ||
    normalized.endsWith('fileid') ||
    normalized.endsWith('fileids')
  );
}

function sanitizedText(value: string): string {
  const sanitized = value
    .replace(/(?:[A-Za-z]:\\|\\\\)[^\s"']+/g, '[已隐藏路径]')
    .replace(/(?<![:\p{L}\p{N}_])\/(?:[^/\s"'<>]+\/)*[^/\s"'<>]+/gu, '[已隐藏路径]')
    .replace(/https?:\/\/[^\s"']+/gi, '[已隐藏地址]')
    .replace(/\b(?:sk|rk)-[A-Za-z0-9_-]{8,}\b/g, '[已隐藏密钥]')
    .replace(
      /\b(password|passwd|pwd|api[_-]?key|access[_-]?token|refresh[_-]?token|session[_-]?token|token|secret|credential|authorization|cookie)\b["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|(?:bearer\s+)?[^\s,;}\]]+)/gi,
      '$1=[已隐藏凭据]'
    )
    .replace(/\bbearer\s+[A-Za-z0-9._~+/-]+=*/gi, 'Bearer [已隐藏凭据]');
  return sanitized.length > 20_000 ? `${sanitized.slice(0, 20_000)}\n[文本已截断]` : sanitized;
}

function isFileRecord(value: Record<string, unknown>): boolean {
  return (
    ('name' in value && 'size_bytes' in value && 'kind' in value) ||
    ('file_id' in value && ('name' in value || 'kind' in value || 'size_bytes' in value)) ||
    ('download_url' in value && 'name' in value)
  );
}

interface SanitizationState {
  fileNumber: number;
  fileAliases: Map<string, string>;
}

function fileAlias(state: SanitizationState, identity?: string): string {
  if (identity) {
    const current = state.fileAliases.get(identity);
    if (current) return current;
  }
  const alias = `F${++state.fileNumber}`;
  if (identity) state.fileAliases.set(identity, alias);
  return alias;
}

function sanitizeFileReferences(
  resource: PlatformInformationResource,
  value: unknown,
  depth: number,
  state: SanitizationState
): unknown {
  if (typeof value === 'string') return fileAlias(state, value);
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeFileReferences(resource, item, depth + 1, state));
  }
  if (!value || typeof value !== 'object') return value;
  if (isFileRecord(value as Record<string, unknown>)) {
    return sanitizeValue(resource, value, depth + 1, state);
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, item]) => [
      key,
      sanitizeFileReferences(resource, item, depth + 1, state)
    ])
  );
}

function sanitizeValue(
  resource: PlatformInformationResource,
  value: unknown,
  depth: number,
  state: SanitizationState
): unknown {
  if (depth > 10) return '[内容层级过深]';
  if (typeof value === 'string') return sanitizedText(value);
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeValue(resource, item, depth + 1, state));
  }
  if (!value || typeof value !== 'object') return value;

  const record = value as Record<string, unknown>;
  const fileRecord = isFileRecord(record);
  const fileIdentity =
    typeof record.file_id === 'string'
      ? record.file_id
      : typeof record.id === 'string'
        ? record.id
        : undefined;
  const hideRecordId = resource === 'users' || resource === 'audit_events' || fileRecord;
  const sanitized = Object.fromEntries(
    Object.entries(record)
      .filter(
        ([key]) =>
          !isSensitiveKey(key) && !(hideRecordId && key === 'id') && !(fileRecord && key === 'name')
      )
      .map(([key, item]) => [
        key,
        normalizedKey(key) === 'files' && (Array.isArray(item) || typeof item === 'object')
          ? sanitizeFileReferences(resource, item, depth + 1, state)
          : sanitizeValue(resource, item, depth + 1, state)
      ])
  );
  return fileRecord ? { alias: fileAlias(state, fileIdentity), ...sanitized } : sanitized;
}

export function sanitizePlatformInformation(
  resource: PlatformInformationResource,
  value: unknown
): unknown {
  return sanitizeValue(resource, value, 0, { fileNumber: 0, fileAliases: new Map() });
}

function checkedPage(value: number | undefined): number {
  return Number.isSafeInteger(value) && Number(value) > 0 ? Math.min(Number(value), 100_000) : 1;
}

function checkedId(value: string | undefined): string {
  const normalized = value?.trim() ?? '';
  if (!normalized || normalized.length > 128) throw new Error('查询明细时必须提供有效的记录标识。');
  return encodeURIComponent(normalized);
}

function pagedPath(base: string, query: PlatformInformationQuery): string {
  const params = new URLSearchParams({
    page: String(checkedPage(query.page)),
    page_size: '20'
  });
  const search = query.query?.trim().slice(0, 100);
  const state = query.state?.trim().slice(0, 40);
  if (search) params.set('query', search);
  if (state) params.set('state', state);
  return `${base}?${params}`;
}

function fetchedDataPath(
  base: string,
  query: PlatformInformationQuery,
  requireDate = false
): string {
  const params = new URLSearchParams({
    dataset: 'ar_groups',
    offset: String((checkedPage(query.page) - 1) * 50),
    limit: '50'
  });
  const search = query.query?.trim().slice(0, 100);
  if (search) params.set('query', search);
  if (query.issues_only) params.set('issues_only', 'true');
  if (requireDate) {
    const date = query.date?.trim() ?? '';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      throw new Error('查询批次取数信息时必须提供核销日期。');
    }
    params.set('reconciliation_date', date);
  }
  return `${base}?${params}`;
}

function offsetPath(base: string, query: PlatformInformationQuery, pageSize = 50): string {
  const params = new URLSearchParams({
    offset: String((checkedPage(query.page) - 1) * pageSize),
    limit: String(pageSize)
  });
  return `${base}?${params}`;
}

function auditEventsPath(query: PlatformInformationQuery): string {
  const params = new URLSearchParams({ limit: '50' });
  const cursor = query.cursor?.trim() ?? '';
  if (cursor) {
    const match = /^audit:(\d+)$/.exec(cursor);
    if (!match) throw new Error('审计记录游标无效。');
    params.set('before_id', match[1]);
  }
  return `/api/admin/audit-events?${params}`;
}

export function platformInformationPath(
  role: PlatformRole,
  query: PlatformInformationQuery
): string {
  if (ADMIN_RESOURCES.has(query.resource) && role !== 'skill_admin') {
    throw new Error('只有平台管理员可以通过 AI 助手查看这类管理信息。');
  }

  switch (query.resource) {
    case 'overview':
      return '/api/workbench';
    case 'skills':
      return '/api/catalog/skills';
    case 'skill_detail':
      return `/api/catalog/skills/${checkedId(query.id)}`;
    case 'task_center':
      return pagedPath('/api/task-center', query);
    case 'files': {
      const path = pagedPath('/api/files', query);
      return `${path}&latest_only=true&include_delete_status=false`;
    }
    case 'file_detail':
      return `/api/files/${checkedId(query.id)}`;
    case 'runs':
      return pagedPath('/api/runs', query);
    case 'run_detail':
      return `/api/runs/${checkedId(query.id)}`;
    case 'run_steps':
      return `/api/runs/${checkedId(query.id)}/steps`;
    case 'run_approvals':
      return `/api/runs/${checkedId(query.id)}/approvals`;
    case 'run_events':
      return offsetPath(`/api/runs/${checkedId(query.id)}/event-history`, query);
    case 'workflows':
      return offsetPath('/api/workflows', query);
    case 'workflow_detail':
      return `/api/workflows/${checkedId(query.id)}`;
    case 'workflow_fetched_data':
      return fetchedDataPath(`/api/workflows/${checkedId(query.id)}/fetched-data`, query);
    case 'workflow_batches':
      return offsetPath('/api/workflow-batches', query);
    case 'workflow_batch_detail':
      return `/api/workflow-batches/${checkedId(query.id)}`;
    case 'workflow_batch_fetched_data':
      return fetchedDataPath(
        `/api/workflow-batches/${checkedId(query.id)}/fetched-data`,
        query,
        true
      );
    case 'task_reminders':
      return '/api/task-reminders';
    case 'profile':
      return '/api/session';
    case 'assistant_status':
      return '/api/assistant/status';
    case 'users':
      return '/api/admin/users';
    case 'audit_events':
      return auditEventsPath(query);
    case 'approvals':
      return query.state
        ? `/api/admin/approvals?status=${encodeURIComponent(query.state.slice(0, 40))}`
        : '/api/admin/approvals';
    case 'model_connections':
      return '/api/model-connections';
    case 'model_providers':
      return '/api/model-providers';
    case 'skill_releases':
      return '/api/admin/skill-releases';
    case 'skill_source_bindings':
      return '/api/admin/skill-sources/bindings';
    case 'skill_availability':
      return '/api/admin/skills/availability';
    case 'skill_dedications':
      return '/api/admin/skill-dedications';
    case 'workflow_definitions':
      return '/api/admin/workflow-definitions';
    case 'observability':
      return '/api/admin/observability/summary?hours=24';
    default:
      throw new Error('不支持的平台信息类型。');
  }
}

export function createPlatformInformationTool(
  role: PlatformRole,
  request: PlatformRequester
): AgentTool {
  return {
    name: 'query_platform_information',
    label: '查询平台信息',
    description:
      '按需读取当前登录账号在平台中有权查看的信息。支持工作台、Skill、任务、文件、工作流、提醒和个人资料；平台管理员还可以读取管理信息。只读，不提供凭据、密钥或文件正文。',
    parameters: Type.Object({
      resource: Type.Union([
        Type.Literal('overview'),
        Type.Literal('skills'),
        Type.Literal('skill_detail'),
        Type.Literal('task_center'),
        Type.Literal('files'),
        Type.Literal('file_detail'),
        Type.Literal('runs'),
        Type.Literal('run_detail'),
        Type.Literal('run_steps'),
        Type.Literal('run_approvals'),
        Type.Literal('run_events'),
        Type.Literal('workflows'),
        Type.Literal('workflow_detail'),
        Type.Literal('workflow_fetched_data'),
        Type.Literal('workflow_batches'),
        Type.Literal('workflow_batch_detail'),
        Type.Literal('workflow_batch_fetched_data'),
        Type.Literal('task_reminders'),
        Type.Literal('profile'),
        Type.Literal('assistant_status'),
        Type.Literal('users'),
        Type.Literal('audit_events'),
        Type.Literal('approvals'),
        Type.Literal('model_connections'),
        Type.Literal('model_providers'),
        Type.Literal('skill_releases'),
        Type.Literal('skill_source_bindings'),
        Type.Literal('skill_availability'),
        Type.Literal('skill_dedications'),
        Type.Literal('workflow_definitions'),
        Type.Literal('observability')
      ]),
      id: Type.Optional(Type.String({ minLength: 1, maxLength: 128 })),
      page: Type.Optional(Type.Integer({ minimum: 1, maximum: 100000 })),
      cursor: Type.Optional(Type.String({ minLength: 1, maxLength: 64 })),
      query: Type.Optional(Type.String({ maxLength: 100 })),
      state: Type.Optional(Type.String({ maxLength: 40 })),
      date: Type.Optional(Type.String({ pattern: '^\\d{4}-\\d{2}-\\d{2}$' })),
      issues_only: Type.Optional(Type.Boolean())
    }),
    execute: async (_toolCallId, params) => {
      const query = params as PlatformInformationQuery;
      const result = await request(platformInformationPath(role, query));
      const sanitizedResult = sanitizePlatformInformation(query.resource, result);
      const sanitized =
        query.resource === 'audit_events' && Array.isArray(result)
          ? {
              items: sanitizedResult,
              next_cursor:
                typeof result.at(-1)?.id === 'number' ? `audit:${result.at(-1)?.id}` : null
            }
          : sanitizedResult;
      return {
        content: [{ type: 'text' as const, text: JSON.stringify(sanitized, null, 2) }],
        details: { resource: query.resource }
      };
    }
  };
}
