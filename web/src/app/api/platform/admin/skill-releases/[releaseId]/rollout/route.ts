import { NextResponse } from 'next/server';
import { startSkillRollout } from '@/features/admin/api/skill-releases';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(request: Request, context: { params: Promise<{ releaseId: string }> }) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '发布请求不是有效的 JSON。');
    }
    const { releaseId } = await context.params;
    return NextResponse.json(await startSkillRollout(releaseId, body), { status: 202 });
  } catch (error) {
    return platformRouteError(error, 'Skill 发布任务创建失败。');
  }
}
