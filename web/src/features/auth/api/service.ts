import 'server-only';

import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/auth/api/types';

export function getPlatformSession(): Promise<PlatformSession> {
  return platformServerRequest<PlatformSession>('/api/session');
}
