import { NextResponse } from 'next/server';
import { updateDisabledSkill } from '@/features/admin/api/skill-releases';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(_request: Request, context: { params: Promise<{ skillId: string }> }) {
  try {
    const { skillId } = await context.params;
    return NextResponse.json(await updateDisabledSkill(skillId));
  } catch (error) {
    return platformRouteError(error, 'Skill 更新失败。');
  }
}
