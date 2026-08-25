import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import {
  platformServerRequest,
  platformServerResponse
} from '@/features/platform-api/server-client';
import type { PlatformFileDetail, PlatformFilePage } from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function checkedUuid(value: string): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, '文件标识格式无效。');
  return value;
}

export function listFiles(
  page = 1,
  pageSize = 20,
  kind = '',
  query = ''
): Promise<PlatformFilePage> {
  const params = new URLSearchParams({
    page: String(Math.max(Math.trunc(page), 1)),
    page_size: String(Math.min(Math.max(Math.trunc(pageSize), 1), 100))
  });
  if (kind) params.set('kind', kind);
  if (query) params.set('query', query.slice(0, 100));
  params.set('latest_only', 'true');
  return platformServerRequest<PlatformFilePage>(`/api/files?${params}`);
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
