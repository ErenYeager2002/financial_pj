import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import {
  platformServerRequest,
  platformServerResponse
} from '@/features/platform-api/server-client';
import type {
  PlatformFile,
  PlatformFileDetail,
  PlatformFileGroupSummaryPage,
  PlatformFileOption,
  PlatformFileOptionPage,
  PlatformFilePage
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function checkedUuid(value: string): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, '文件标识格式无效。');
  return value;
}

export interface ListFilesOptions {
  page?: number;
  pageSize?: number;
  kind?: string;
  query?: string;
  includeDeleteStatus?: boolean;
  skillId?: string;
  unassigned?: boolean;
}

export function listFiles({
  page = 1,
  pageSize = 25,
  kind = '',
  query = '',
  includeDeleteStatus = true,
  skillId = '',
  unassigned = false
}: ListFilesOptions = {}): Promise<PlatformFilePage> {
  const params = new URLSearchParams({
    page: String(Math.max(Math.trunc(page), 1)),
    page_size: String(Math.min(Math.max(Math.trunc(pageSize), 1), 100))
  });
  if (kind) params.set('kind', kind);
  const checkedQuery = query.trim().slice(0, 100);
  if (checkedQuery) params.set('query', checkedQuery);
  params.set('latest_only', 'true');
  if (!includeDeleteStatus) params.set('include_delete_status', 'false');
  const checkedSkillId = skillId.trim().slice(0, 128);
  if (checkedSkillId) params.set('skill_id', checkedSkillId);
  if (unassigned) params.set('unassigned', 'true');
  return platformServerRequest<PlatformFilePage>(`/api/files?${params}`);
}

export interface ListFileGroupsOptions {
  kind?: string;
  query?: string;
  latestOnly?: boolean;
}

export function listFileGroups({
  kind = '',
  query = '',
  latestOnly = true
}: ListFileGroupsOptions = {}): Promise<PlatformFileGroupSummaryPage> {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);
  const checkedQuery = query.trim().slice(0, 100);
  if (checkedQuery) params.set('query', checkedQuery);
  params.set('latest_only', String(latestOnly));
  return platformServerRequest<PlatformFileGroupSummaryPage>(`/api/files/groups?${params}`);
}

function selectableInputFileParams(
  page: number,
  pageSize: number,
  query = '',
  fileIds: string[] = []
): URLSearchParams {
  const params = new URLSearchParams({
    page: String(Math.max(Math.trunc(page), 1)),
    page_size: String(Math.min(Math.max(Math.trunc(pageSize), 1), 100))
  });
  if (query) params.set('query', query.slice(0, 100));
  if (fileIds.length) params.set('ids', fileIds.map(checkedUuid).join(','));
  return params;
}

export function listSelectableInputFilesPage(
  page = 1,
  pageSize = 25,
  query = ''
): Promise<PlatformFileOptionPage> {
  const params = selectableInputFileParams(page, pageSize, query);
  return platformServerRequest<PlatformFileOptionPage>(
    `/api/files/selectable-inputs?${params}`
  );
}

export async function listSelectableInputFilesByIds(
  fileIds: string[]
): Promise<PlatformFileOption[]> {
  if (!fileIds.length) return [];
  const checkedFileIds = fileIds.map(checkedUuid);
  const params = selectableInputFileParams(1, checkedFileIds.length, '', checkedFileIds);
  const result = await platformServerRequest<PlatformFileOptionPage>(
    `/api/files/selectable-inputs?${params}`
  );
  return result.items ?? [];
}

export function getFile(fileId: string): Promise<PlatformFileDetail> {
  return platformServerRequest<PlatformFileDetail>(`/api/files/${checkedUuid(fileId)}`);
}

export function deleteFile(fileId: string): Promise<null> {
  return platformServerRequest<null>(`/api/files/${checkedUuid(fileId)}`, { method: 'DELETE' });
}

export async function downloadFile(
  fileId: string,
  signal: AbortSignal
): Promise<{ response: Response; file: PlatformFileDetail }> {
  const checkedFileId = checkedUuid(fileId);
  const file = await getFile(checkedFileId);
  const response = await platformServerResponse(
    `/api/files/${checkedFileId}/download`,
    { signal },
    { timeoutMs: 120_000 }
  );
  return { response, file };
}
