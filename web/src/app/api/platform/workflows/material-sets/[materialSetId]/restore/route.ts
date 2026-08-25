import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { restoreWorkflowMaterialSet } from '@/features/workflow-agent/api/server';

const ID = /^[A-Za-z0-9._-]+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(
  request: Request,
  context: { params: Promise<{ materialSetId: string }> }
): Promise<Response> {
  try {
    const { materialSetId } = await context.params;
    const skillId = new URL(request.url).searchParams.get('skill_id')?.trim() ?? '';
    if (!UUID.test(materialSetId)) throw new PlatformApiError(400, '业务版本标识格式无效。');
    if (!ID.test(skillId)) throw new PlatformApiError(400, 'Skill 标识格式无效。');
    return NextResponse.json(await restoreWorkflowMaterialSet(skillId, materialSetId));
  } catch (error) {
    return platformRouteError(error, '业务材料历史版本恢复失败。');
  }
}
