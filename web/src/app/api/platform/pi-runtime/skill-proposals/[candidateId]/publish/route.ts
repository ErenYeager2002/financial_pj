import {NextResponse} from 'next/server';
import {platformServerRequest} from '@/features/platform-api/server-client';
import {platformRouteError} from '@/features/platform-api/route-handler';
export async function POST(request:Request,context:{params:Promise<{candidateId:string}>}){try{const {candidateId}=await context.params;return NextResponse.json(await platformServerRequest(`/api/pi-runtime/skill-proposals/${encodeURIComponent(candidateId)}/publish`,{method:'POST',body:JSON.stringify(await request.json())}))}catch(error){return platformRouteError(error,'发布失败')}}
