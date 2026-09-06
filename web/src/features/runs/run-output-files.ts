import type { PlatformRunDetail, RunOutputFile } from './api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseRunOutputFiles(run: PlatformRunDetail): RunOutputFile[] {
  const raw = run.result?.output_files;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!isRecord(item)) return [];
    const fileId = typeof item.file_id === 'string' ? item.file_id : '';
    const name = typeof item.name === 'string' ? item.name : '';
    const sizeBytes = typeof item.size_bytes === 'number' ? item.size_bytes : 0;
    const sha256 = typeof item.sha256 === 'string' ? item.sha256 : '';
    if (!UUID.test(fileId) || !name || sizeBytes < 0) return [];
    return [{ fileId, name, sizeBytes, sha256 }];
  });
}

export function runOutputFileDownloadHref(fileId: string): string {
  return `/api/platform/files/${encodeURIComponent(fileId)}/download`;
}
