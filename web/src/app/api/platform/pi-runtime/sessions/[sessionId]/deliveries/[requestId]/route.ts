import { NextResponse } from 'next/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET(
  _request: Request,
  context: { params: Promise<{ sessionId: string; requestId: string }> }
) {
  try {
    const { sessionId, requestId } = await context.params;
    return NextResponse.json(await platformServerRequest(
      `/api/pi-runtime/sessions/${encodeURIComponent(sessionId)}/deliveries/${encodeURIComponent(requestId)}`
    ));
  } catch (error) {
    return platformRouteError(error, '消息投递回执查询失败。');
  }
}
