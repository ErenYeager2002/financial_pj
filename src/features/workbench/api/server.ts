import 'server-only';

import { platformServerRequest } from '@/features/platform-api/server-client';
import type { Workbench } from '@/features/platform-api/types';

export function getWorkbench(): Promise<Workbench> {
  return platformServerRequest<Workbench>('/api/workbench');
}
