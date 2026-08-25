import { NextResponse } from 'next/server';
import { prepareSkillSourceRelease } from '@/features/admin/api/skill-releases';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(request: Request, context: { params: Promise<{ skillId: string }> }) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '发布准备请求不是有效的 JSON。');
    }
    const { skillId } = await context.params;
    return NextResponse.json(await prepareSkillSourceRelease(skillId, body), { status: 201 });
  } catch (error) {
    return platformRouteError(error, 'Skill 发布包准备失败。');
  }
}
