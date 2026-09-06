import type { PlatformFileGroupSummary } from '@/features/platform-api/types';

export const FILE_CENTER_PAGE_SIZES = [25, 50] as const;
export type FileCenterPageSize = (typeof FILE_CENTER_PAGE_SIZES)[number];
export type FileCenterPaginationItem = number | 'ellipsis';

export function normalizeFileCenterPageSize(value: number | string | undefined): FileCenterPageSize {
  return Number(value) === 50 ? 50 : 25;
}

export function fileGroupKey(group: Pick<PlatformFileGroupSummary, 'skill_id' | 'unassigned'>): string {
  return group.unassigned ? 'unassigned' : `skill:${group.skill_id}`;
}

export function fileCenterPaginationItems(page: number, pages: number): FileCenterPaginationItem[] {
  if (pages <= 0) return [];
  const currentPage = Math.min(Math.max(Math.trunc(page), 1), pages);
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  if (currentPage <= 4) return [1, 2, 3, 4, 5, 'ellipsis', pages];
  if (currentPage >= pages - 3) {
    return [1, 'ellipsis', pages - 4, pages - 3, pages - 2, pages - 1, pages];
  }
  return [
    1,
    'ellipsis',
    currentPage - 1,
    currentPage,
    currentPage + 1,
    'ellipsis',
    pages
  ];
}

export interface FileCenterUrlState {
  kind?: string;
  query?: string;
  group?: Pick<PlatformFileGroupSummary, 'skill_id' | 'unassigned'> | null;
  page?: number;
  pageSize?: number | string;
}

export interface FileCenterSearchParams {
  kind?: string;
  query?: string;
  skill_id?: string;
  unassigned?: string;
  page?: string;
  page_size?: string;
}

export interface FileCenterQueryState {
  kind: string;
  query: string;
  requestedSkillId: string;
  unassigned: boolean;
  pageSize: FileCenterPageSize;
  requestedPage: number;
  pageWasNormalized: boolean;
  hasExplicitSkillId: boolean;
}

export interface ResolvedFileCenterState extends FileCenterQueryState {
  activeGroup: PlatformFileGroupSummary | null;
  page: number;
  requestedGroupFound: boolean;
}

function readFileCenterParam(value: string | undefined): string {
  return value ?? '';
}

export function parseFileCenterSearchParams(
  params: FileCenterSearchParams
): FileCenterQueryState {
  const rawSkillId = readFileCenterParam(params.skill_id).trim().slice(0, 128);
  const unassigned = params.unassigned === 'true';
  const rawPageParam = readFileCenterParam(params.page);
  const rawPage = Number(rawPageParam || '1');
  const requestedPage =
    Number.isSafeInteger(rawPage) && rawPage > 0 ? Math.min(rawPage, 100_000) : 1;
  return {
    kind: ['input', 'output'].includes(params.kind ?? '') ? (params.kind ?? '') : '',
    query: readFileCenterParam(params.query).trim().slice(0, 100),
    requestedSkillId: unassigned ? '' : rawSkillId,
    unassigned,
    pageSize: normalizeFileCenterPageSize(params.page_size),
    requestedPage,
    pageWasNormalized:
      Boolean(rawPageParam) &&
      (!Number.isSafeInteger(rawPage) ||
        rawPage < 1 ||
        rawPage > 100_000 ||
        rawPageParam !== String(rawPage)),
    hasExplicitSkillId: Boolean(rawSkillId)
  };
}

export function resolveFileCenterState(
  state: FileCenterQueryState,
  groups: PlatformFileGroupSummary[]
): ResolvedFileCenterState {
  const activeGroup =
    groups.find((group) =>
      state.requestedSkillId
        ? !group.unassigned && group.skill_id === state.requestedSkillId
        : state.unassigned
          ? group.unassigned
          : false
    ) ?? groups[0] ?? null;
  const requestedGroupFound =
    state.requestedSkillId || state.unassigned
      ? Boolean(
          activeGroup &&
            (state.requestedSkillId
              ? !activeGroup.unassigned && activeGroup.skill_id === state.requestedSkillId
              : activeGroup.unassigned)
        )
      : !state.hasExplicitSkillId;
  const activeGroupPages = activeGroup
    ? Math.ceil(activeGroup.file_count / state.pageSize)
    : 0;
  return {
    ...state,
    activeGroup,
    page: requestedGroupFound
      ? Math.min(state.requestedPage, Math.max(activeGroupPages, 1))
      : 1,
    requestedGroupFound
  };
}

export function fileCenterSearchParams(state: FileCenterUrlState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.kind) params.set('kind', state.kind);
  const query = state.query?.trim().slice(0, 100);
  if (query) params.set('query', query);
  if (state.group?.unassigned) params.set('unassigned', 'true');
  else if (state.group?.skill_id) params.set('skill_id', state.group.skill_id);
  params.set('page', String(Math.max(Math.trunc(state.page ?? 1), 1)));
  params.set('page_size', String(normalizeFileCenterPageSize(state.pageSize)));
  return params;
}

export function fileCenterUrl(state: FileCenterUrlState): string {
  return `/dashboard/files?${fileCenterSearchParams(state).toString()}`;
}

export function pageAfterFileDelete(page: number, itemCount: number): number {
  return page > 1 && itemCount <= 1 ? page - 1 : Math.max(page, 1);
}
