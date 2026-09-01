import 'server-only';

import { platformServerRequest } from '@/features/platform-api/server-client';
import type { TaskCenterPage } from '@/features/platform-api/types';
import { taskCenterApiPath, type TaskCenterQuery } from '@/features/task-center/query';

export function getTaskCenterPage(query: TaskCenterQuery): Promise<TaskCenterPage> {
  return platformServerRequest<TaskCenterPage>(taskCenterApiPath(query));
}
