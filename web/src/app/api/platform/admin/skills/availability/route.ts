import { NextResponse } from 'next/server';
import { listSkillAvailability } from '@/features/admin/api/skill-releases';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listSkillAvailability());
  } catch (error) {
    return platformRouteError(error, 'Skill 可用状态清单读取失败。');
  }
}
