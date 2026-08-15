import { NextResponse } from 'next/server';
import { listSkillReleases } from '@/features/admin/api/skill-releases';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listSkillReleases());
  } catch (error) {
    return platformRouteError(error, 'Skill 发布记录加载失败。');
  }
}
