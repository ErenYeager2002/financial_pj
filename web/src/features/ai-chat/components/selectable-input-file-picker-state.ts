import type { PlatformFileOptionPage } from '@/features/platform-api/types';

export const MAX_SELECTED_FILES = 20;

export function normalizeSelectedFileLimit(value = MAX_SELECTED_FILES): number {
  if (!Number.isFinite(value)) return MAX_SELECTED_FILES;
  return Math.min(MAX_SELECTED_FILES, Math.max(0, Math.trunc(value)));
}

export function toggleSelectedFileIds(
  selectedFileIds: readonly string[],
  fileId: string,
  checked: boolean,
  maxSelectedFiles = MAX_SELECTED_FILES
): string[] {
  const limit = normalizeSelectedFileLimit(maxSelectedFiles);
  if (!checked) return selectedFileIds.filter((item) => item !== fileId);
  if (selectedFileIds.includes(fileId) || selectedFileIds.length >= limit) {
    return [...selectedFileIds];
  }
  return [...selectedFileIds, fileId];
}

export function isSelectableInputFileDisabled(
  selectedFileIds: readonly string[],
  fileId: string,
  disabled: boolean,
  maxSelectedFiles = MAX_SELECTED_FILES
): boolean {
  const limit = normalizeSelectedFileLimit(maxSelectedFiles);
  return disabled || (selectedFileIds.length >= limit && !selectedFileIds.includes(fileId));
}

export function selectedFileLimitMessage(
  selectedCount: number,
  maxSelectedFiles = MAX_SELECTED_FILES
): string | null {
  const limit = normalizeSelectedFileLimit(maxSelectedFiles);
  return selectedCount >= limit ? `最多选择 ${limit} 个文件。` : null;
}

export function selectedFileCountMessage(
  selectedCount: number,
  maxSelectedFiles = MAX_SELECTED_FILES
): string {
  return `已选择 ${selectedCount} / ${normalizeSelectedFileLimit(maxSelectedFiles)} 个文件`;
}

export type SelectableInputFilePageFetcher = (
  input: RequestInfo | URL,
  init?: RequestInit
) => Promise<Response>;

export function createSelectableInputFilePageLoader(
  fetcher: SelectableInputFilePageFetcher = fetch
) {
  let activeController: AbortController | null = null;

  return {
    async request(
      page: number,
      pageSize: number,
      query = ''
    ): Promise<PlatformFileOptionPage | null> {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      const params = new URLSearchParams({
        page: String(Math.max(Math.trunc(page), 1)),
        page_size: String(Math.min(Math.max(Math.trunc(pageSize), 1), 100))
      });
      const normalizedQuery = query.trim().slice(0, 100);
      if (normalizedQuery) params.set('query', normalizedQuery);

      try {
        const response = await fetcher(`/api/platform/files/selectable-inputs?${params}`, {
          cache: 'no-store',
          signal: controller.signal
        });
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(body?.detail ?? '可选文件加载失败。');
        }
        const nextPage = (await response.json()) as PlatformFileOptionPage;
        return controller.signal.aborted ? null : nextPage;
      } catch (error) {
        if (controller.signal.aborted) return null;
        throw error;
      } finally {
        if (activeController === controller) activeController = null;
      }
    },
    cancel() {
      activeController?.abort();
      activeController = null;
    }
  };
}
