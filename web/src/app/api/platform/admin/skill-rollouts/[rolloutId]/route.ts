import { NextResponse } from 'next/server';
import { getSkillRollout } from '@/features/admin/api/skill-releases';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET(_request: Request, context: { params: Promise<{ rolloutId: string }> }) {
  try {
    const { rolloutId } = await context.params;
    return NextResponse.json(await getSkillRollout(rolloutId));
  } catch (error) {
    return platformRouteError(error, 'Skill 发布状态读取失败。');
  }
}
