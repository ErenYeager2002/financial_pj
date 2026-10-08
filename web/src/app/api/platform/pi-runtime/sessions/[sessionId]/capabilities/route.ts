import {NextResponse} from 'next/server';
import {platformServerRequest} from '@/features/platform-api/server-client';
import {platformRouteError} from '@/features/platform-api/route-handler';
export async function GET(_request:Request,context:{params:Promise<{sessionId:string}>}){
 try{const {sessionId}=await context.params;return NextResponse.json(await platformServerRequest(`/api/pi-runtime/sessions/${encodeURIComponent(sessionId)}/capabilities`),{headers:{'Cache-Control':'no-store'}})}catch(error){return platformRouteError(error,'会话权限读取失败。')}
}
