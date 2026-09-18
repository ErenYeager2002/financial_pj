import { NextResponse } from 'next/server';
import { platformServerResponse } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
export async function POST(request: Request, context: { params: Promise<{ sessionId: string }> }) {
 try {
  const { sessionId } = await context.params;
  const response = await platformServerResponse(`/api/pi-runtime/sessions/${encodeURIComponent(sessionId)}/files`, {method:'POST',body:JSON.stringify(await request.json())}, {timeoutMs:120_000});
  return NextResponse.json(await response.json());
 } catch(error) { return platformRouteError(error,'Pi 文件操作失败。'); }
}
