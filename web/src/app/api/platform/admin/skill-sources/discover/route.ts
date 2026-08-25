import { NextResponse } from 'next/server';
import { discoverSkillSources } from '@/features/admin/api/skill-releases';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST() {
  try {
    return NextResponse.json(await discoverSkillSources());
  } catch (error) {
    return platformRouteError(error, 'Gitee Skill 发现失败。');
  }
}
