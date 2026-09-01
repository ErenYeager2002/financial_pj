export type TaskCenterQuery = {
  page: number;
};

export type TaskCenterRawQuery = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? '';
}

export function parseTaskCenterQuery(raw: TaskCenterRawQuery): TaskCenterQuery {
  const parsedPage = Number.parseInt(first(raw.page), 10);
  return {
    page: Number.isSafeInteger(parsedPage) && parsedPage > 0 ? Math.min(parsedPage, 100_000) : 1
  };
}

export function hasTaskCenterUnsupportedParams(raw: TaskCenterRawQuery): boolean {
  return Object.keys(raw).some((key) => key !== 'page');
}

function frontendParams(page: number): URLSearchParams {
  const params = new URLSearchParams();
  if (page > 1) params.set('page', String(page));
  return params;
}

export function taskCenterHref(query: TaskCenterQuery, page = query.page): string {
  const params = frontendParams(page);
  return `/dashboard/runs${params.size ? `?${params}` : ''}`;
}

export function taskCenterPageRedirect(query: TaskCenterQuery, pages: number): string | null {
  return pages > 0 && query.page > pages ? taskCenterHref(query, pages) : null;
}

export function taskCenterApiPath(query: TaskCenterQuery, pageSize = 5): string {
  const checkedPageSize = Math.min(Math.max(Math.trunc(pageSize), 1), 100);
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(checkedPageSize)
  });
  return `/api/task-center?${params}`;
}

export function taskCenterBrowserPath(query: TaskCenterQuery, pageSize = 5): string {
  return taskCenterApiPath(query, pageSize).replace(
    '/api/task-center',
    '/api/platform/task-center'
  );
}
