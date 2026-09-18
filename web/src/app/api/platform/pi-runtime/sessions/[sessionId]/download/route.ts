import { platformServerResponse } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
export async function GET(request: Request, context: { params: Promise<{ sessionId: string }> }) {
 try {
  const { sessionId } = await context.params;
  const incoming=new URL(request.url);
  const query=new URLSearchParams({path:incoming.searchParams.get('path')??'',source:incoming.searchParams.get('source')??'workspace'});
  const response=await platformServerResponse(`/api/pi-runtime/sessions/${encodeURIComponent(sessionId)}/download?${query}`, {signal:request.signal}, {timeoutMs:null});
  const headers=new Headers();
  for(const key of ['Content-Type','Content-Length','Content-Disposition','Cache-Control','X-Content-Type-Options']) {
   const value=response.headers.get(key);if(value)headers.set(key,value);
  }
  return new Response(response.body,{status:response.status,headers});
 } catch(error) { return platformRouteError(error,'Pi 文件下载失败。'); }
}
