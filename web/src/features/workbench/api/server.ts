import 'server-only';

import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformHealth, RuntimeHealth, Workbench } from '@/features/platform-api/types';

export function getWorkbench(): Promise<Workbench> {
  return platformServerRequest<Workbench>('/api/workbench');
}

export async function getPlatformHealth(): Promise<PlatformHealth> {
  const liveness = await platformServerRequest<PlatformHealth>('/api/health');
  try {
    const runtime = await platformServerRequest<RuntimeHealth>('/api/health/readiness');
    return { ...liveness, ...runtime };
  } catch {
    return {
      ...liveness,
      readiness: 'unknown',
      dependency_status: 'unknown',
      checked_at: null,
      online_workers: {},
      queue_depth: {},
      workers: [],
      scope: '运行状态暂未检查。'
    };
  }
}
