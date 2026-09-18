import {NextResponse} from 'next/server';
import {platformServerRequest} from '@/features/platform-api/server-client';
import {platformRouteError} from '@/features/platform-api/route-handler';
export async function GET(){try{return NextResponse.json(await platformServerRequest('/api/pi-runtime/skill-proposals'))}catch(error){return platformRouteError(error,'读取发布草稿失败')}}
