import { NextResponse } from 'next/server';
import { listSkillDedications } from '@/features/admin/api/skill-dedications';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listSkillDedications());
  } catch (error) {
    return platformRouteError(error, 'Skill 专属员工标记加载失败。');
  }
}
