import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';

export async function GET() {
  try {
    const session = await platformServerRequest<PlatformSession>('/api/session');
    return NextResponse.json(session);
  } catch (error) {
    return platformRouteError(error, '财务平台暂时不可用。');
  }
}
