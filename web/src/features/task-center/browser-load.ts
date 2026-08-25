import type { TaskCenterPage, TaskReminderBoard } from '@/features/platform-api/types';
import {
  hasTaskCenterFilters,
  taskCenterBrowserPath,
  taskCenterPageRedirect,
  type TaskCenterQuery
} from './query.ts';

export type RegionRequest = (input: string, init?: RequestInit) => Promise<Response>;

async function readJson<T>(request: RegionRequest, path: string): Promise<T> {
  const response = await request(path, { cache: 'no-store' });
  if (response.status === 401 || response.status === 403) {
    throw Object.assign(new Error('authorization'), { status: response.status });
  }
  if (!response.ok) throw new Error('region request failed');
  return (await response.json()) as T;
}

export function loadTaskReminderRegion(request: RegionRequest = fetch): Promise<TaskReminderBoard> {
  return readJson<TaskReminderBoard>(request, '/api/platform/task-reminders');
}

export async function loadFormalTaskRegion(
  query: TaskCenterQuery,
  request: RegionRequest = fetch
): Promise<{ page: TaskCenterPage; hasAnyTasks: boolean; canonicalHref: string | null }> {
  const page = await readJson<TaskCenterPage>(request, taskCenterBrowserPath(query));
  let hasAnyTasks = page.total > 0;
  if (!hasAnyTasks && hasTaskCenterFilters(query)) {
    const unfiltered: TaskCenterQuery = {
      page: 1,
      state: '',
      type: '',
      skill: '',
      businessFrom: '',
      businessTo: '',
      updatedFrom: '',
      updatedTo: ''
    };
    const allTasks = await readJson<TaskCenterPage>(request, taskCenterBrowserPath(unfiltered, 1));
    hasAnyTasks = allTasks.total > 0;
  }
  return {
    page,
    hasAnyTasks,
    canonicalHref: taskCenterPageRedirect(query, page.pages)
  };
}
