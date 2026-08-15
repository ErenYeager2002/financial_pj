import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { listSkillCatalog } from '@/features/skills/api/server';

export async function GET() {
  try {
    return NextResponse.json(await listSkillCatalog());
  } catch (error) {
    return platformRouteError(error, 'Skill 目录暂时不可用。');
  }
}
