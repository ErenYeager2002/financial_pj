import { NextResponse } from 'next/server';
import { listSkillReleaseInbox } from '@/features/admin/api/skill-releases';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listSkillReleaseInbox());
  } catch (error) {
    return platformRouteError(error, 'Skill 发布包收件箱加载失败。');
  }
}
