const VIEW_STATES = new Set(['pending', 'running', 'failed', 'succeeded', 'cancelled']);
const ITEM_TYPES = new Set(['run', 'workflow', 'workflow_batch']);
const DATE_VALUE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME_VALUE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/;

export type TaskCenterQuery = {
  page: number;
  state: string;
  type: string;
  skill: string;
  businessFrom: string;
  businessTo: string;
  updatedFrom: string;
  updatedTo: string;
};

export type TaskCenterRawQuery = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? '';
}

function accepted(value: string, values: Set<string>): string {
  return values.has(value) ? value : '';
}

function dateValue(value: string): string {
  if (!DATE_VALUE.test(value)) return '';
  const [year, month, day] = value.split('-').map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
    ? value
    : '';
}

function dateTimeValue(value: string): string {
  if (!DATE_TIME_VALUE.test(value)) return '';
  const [datePart, timePart] = value.split('T');
  const timeParts = timePart.split(':');
  const hour = Number(timeParts[0]);
  const minute = Number(timeParts[1]);
  const second = Number(timeParts[2] ?? '0');
  return dateValue(datePart) && hour <= 23 && minute <= 59 && second <= 59 ? value : '';
}

export function parseTaskCenterQuery(raw: TaskCenterRawQuery): TaskCenterQuery {
  const parsedPage = Number.parseInt(first(raw.page), 10);
  const businessFrom = dateValue(first(raw.business_from));
  const businessTo = dateValue(first(raw.business_to));
  const updatedFrom = dateTimeValue(first(raw.updated_from));
  const updatedTo = dateTimeValue(first(raw.updated_to));
  const businessRangeValid = !businessFrom || !businessTo || businessFrom <= businessTo;
  const updatedRangeValid = !updatedFrom || !updatedTo || updatedFrom <= updatedTo;
  return {
    page: Number.isSafeInteger(parsedPage) && parsedPage > 0 ? Math.min(parsedPage, 100_000) : 1,
    state: accepted(first(raw.state), VIEW_STATES),
    type: accepted(first(raw.type), ITEM_TYPES),
    skill: first(raw.skill).slice(0, 100),
    businessFrom: businessRangeValid ? businessFrom : '',
    businessTo: businessRangeValid ? businessTo : '',
    updatedFrom: updatedRangeValid ? updatedFrom : '',
    updatedTo: updatedRangeValid ? updatedTo : ''
  };
}

export function hasTaskCenterFilters(query: TaskCenterQuery): boolean {
  return Boolean(
    query.state ||
    query.type ||
    query.skill ||
    query.businessFrom ||
    query.businessTo ||
    query.updatedFrom ||
    query.updatedTo
  );
}

function frontendParams(query: TaskCenterQuery, page = query.page): URLSearchParams {
  const params = new URLSearchParams();
  if (page > 1) params.set('page', String(page));
  if (query.state) params.set('state', query.state);
  if (query.type) params.set('type', query.type);
  if (query.skill) params.set('skill', query.skill);
  if (query.businessFrom) params.set('business_from', query.businessFrom);
  if (query.businessTo) params.set('business_to', query.businessTo);
  if (query.updatedFrom) params.set('updated_from', query.updatedFrom);
  if (query.updatedTo) params.set('updated_to', query.updatedTo);
  return params;
}

function shanghaiDateTime(value: string): string {
  return `${value.length === 16 ? `${value}:00` : value}+08:00`;
}

export function taskCenterHref(query: TaskCenterQuery, page = query.page): string {
  const params = frontendParams(query, page);
  return `/dashboard/runs${params.size ? `?${params}` : ''}`;
}

export function taskCenterPageRedirect(query: TaskCenterQuery, pages: number): string | null {
  return pages > 0 && query.page > pages ? taskCenterHref(query, pages) : null;
}

export function taskCenterApiPath(query: TaskCenterQuery, pageSize = 20): string {
  const checkedPageSize = Math.min(Math.max(Math.trunc(pageSize), 1), 100);
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(checkedPageSize)
  });
  if (query.state) params.set('view_state', query.state);
  if (query.type) params.set('item_type', query.type);
  if (query.skill) params.set('skill_id', query.skill);
  if (query.businessFrom) params.set('business_date_from', query.businessFrom);
  if (query.businessTo) params.set('business_date_to', query.businessTo);
  if (query.updatedFrom) params.set('updated_from', shanghaiDateTime(query.updatedFrom));
  if (query.updatedTo) params.set('updated_to', shanghaiDateTime(query.updatedTo));
  return `/api/task-center?${params}`;
}

export function taskCenterBrowserPath(query: TaskCenterQuery, pageSize = 20): string {
  return taskCenterApiPath(query, pageSize).replace(
    '/api/task-center',
    '/api/platform/task-center'
  );
}
