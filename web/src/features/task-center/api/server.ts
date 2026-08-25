import 'server-only';

import { platformServerRequest } from '@/features/platform-api/server-client';
import type { TaskCenterPage } from '@/features/platform-api/types';
import { taskCenterApiPath, type TaskCenterQuery } from '@/features/task-center/query';

const EMPTY_QUERY: TaskCenterQuery = {
  page: 1,
  state: '',
  type: '',
  skill: '',
  businessFrom: '',
  businessTo: '',
  updatedFrom: '',
  updatedTo: ''
};

export function getTaskCenterPage(query: TaskCenterQuery): Promise<TaskCenterPage> {
  return platformServerRequest<TaskCenterPage>(taskCenterApiPath(query));
}

export async function hasAnyFormalTask(): Promise<boolean> {
  const result = await platformServerRequest<TaskCenterPage>(taskCenterApiPath(EMPTY_QUERY, 1));
  return result.total > 0;
}
