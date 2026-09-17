import { NextResponse } from 'next/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
export async function GET(request: Request, { params }: {params: Promise<{skillId: string}>}) {
  try { const {skillId}=await params; const session = new URL(request.url).searchParams.get('session_id') ?? '';
    return NextResponse.json(await platformServerRequest(`/api/assistant/native-skills/${encodeURIComponent(skillId)}/runs?session_id=${encodeURIComponent(session)}`));
  } catch(error) { return platformRouteError(error,'Skill 执行记录读取失败。'); }
}
