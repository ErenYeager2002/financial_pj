import { NextResponse } from 'next/server';
import {
  getSkillAvailability,
  transitionSkillAvailability
} from '@/features/admin/api/skill-releases';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET(_request: Request, context: { params: Promise<{ skillId: string }> }) {
  try {
    const { skillId } = await context.params;
    return NextResponse.json(await getSkillAvailability(skillId));
  } catch (error) {
    return platformRouteError(error, 'Skill 可用状态读取失败。');
  }
}

export async function POST(request: Request, context: { params: Promise<{ skillId: string }> }) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, 'Skill 状态变更请求不是有效的 JSON。');
    }
    const { skillId } = await context.params;
    return NextResponse.json(await transitionSkillAvailability(skillId, body));
  } catch (error) {
    return platformRouteError(error, 'Skill 可用状态变更失败。');
  }
}
