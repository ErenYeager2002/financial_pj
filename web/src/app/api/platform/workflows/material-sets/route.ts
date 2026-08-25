import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { listWorkflowMaterialSets } from '@/features/workflow-agent/api/server';

const ID = /^[A-Za-z0-9._-]+$/;

export async function GET(request: Request): Promise<Response> {
  try {
    const skillId = new URL(request.url).searchParams.get('skill_id')?.trim() ?? '';
    if (!ID.test(skillId)) throw new PlatformApiError(400, 'Skill 标识格式无效。');
    return NextResponse.json(await listWorkflowMaterialSets(skillId));
  } catch (error) {
    return platformRouteError(error, '业务材料历史版本加载失败。');
  }
}
