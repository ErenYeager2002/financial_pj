export type TaskCenterQuery = {
  page: number;
  pageSize: number;
  query: string;
  skillId: string;
  viewState: 'pending' | 'running' | 'failed' | 'succeeded' | 'cancelled' | '';
  businessDateFrom: string;
  businessDateTo: string;
};

export type TaskCenterRawQuery = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? '';
}

export function parseTaskCenterQuery(raw: TaskCenterRawQuery): TaskCenterQuery {
  const parsedPage = Number.parseInt(first(raw.page), 10);
  const parsedPageSize = Number.parseInt(first(raw.page_size), 10);
  const rawViewState = first(raw.view_state);
  const viewState = ['pending', 'running', 'failed', 'succeeded', 'cancelled'].includes(rawViewState)
    ? (rawViewState as TaskCenterQuery['viewState'])
    : '';
  return {
    page: Number.isSafeInteger(parsedPage) && parsedPage > 0 ? Math.min(parsedPage, 100_000) : 1,
    pageSize:
      Number.isSafeInteger(parsedPageSize) && parsedPageSize >= 5 && parsedPageSize <= 100
        ? parsedPageSize
        : 10,
    query: first(raw.query).slice(0, 128),
    skillId: first(raw.skill_id).slice(0, 128),
    viewState,
    businessDateFrom: first(raw.business_date_from),
    businessDateTo: first(raw.business_date_to)
  };
}

export function hasTaskCenterUnsupportedParams(raw: TaskCenterRawQuery): boolean {
  const supported = new Set([
    'page',
    'page_size',
    'query',
    'skill_id',
    'view_state',
    'business_date_from',
    'business_date_to'
  ]);
  return Object.keys(raw).some((key) => !supported.has(key));
}

function frontendParams(query: TaskCenterQuery, page: number): URLSearchParams {
  const params = new URLSearchParams();
  if (page > 1) params.set('page', String(page));
  if (query.pageSize !== 10) params.set('page_size', String(query.pageSize));
  if (query.query) params.set('query', query.query);
  if (query.skillId) params.set('skill_id', query.skillId);
  if (query.viewState) params.set('view_state', query.viewState);
  if (query.businessDateFrom) params.set('business_date_from', query.businessDateFrom);
  if (query.businessDateTo) params.set('business_date_to', query.businessDateTo);
  return params;
}

export function taskCenterHref(
  query: TaskCenterQuery,
  page = query.page,
  overrides: Partial<TaskCenterQuery> = {}
): string {
  const nextQuery = { ...query, ...overrides };
  const params = frontendParams(nextQuery, page);
  return `/dashboard/runs${params.size ? `?${params}` : ''}`;
}

export function taskCenterPageRedirect(query: TaskCenterQuery, pages: number): string | null {
  const lastPage = Math.max(1, pages);
  if (query.page <= lastPage) return null;
  return taskCenterHref(query, lastPage);
}

export function taskCenterApiPath(query: TaskCenterQuery, pageSize?: number): string {
  const checkedPageSize = Math.min(Math.max(Math.trunc(pageSize ?? query.pageSize), 1), 100);
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(checkedPageSize),
    ...(query.query ? { query: query.query } : {}),
    ...(query.skillId ? { skill_id: query.skillId } : {}),
    ...(query.viewState ? { view_state: query.viewState } : {}),
    ...(query.businessDateFrom ? { business_date_from: query.businessDateFrom } : {}),
    ...(query.businessDateTo ? { business_date_to: query.businessDateTo } : {})
  });
  return `/api/task-center?${params}`;
}

export function taskCenterBrowserPath(query: TaskCenterQuery, pageSize?: number): string {
  return taskCenterApiPath(query, pageSize).replace(
    '/api/task-center',
    '/api/platform/task-center'
  );
}
