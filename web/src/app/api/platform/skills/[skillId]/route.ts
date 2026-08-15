import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { getSkillCatalogItem } from '@/features/skills/api/server';

type Params = { params: Promise<{ skillId: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const { skillId } = await params;
    return NextResponse.json(await getSkillCatalogItem(skillId));
  } catch (error) {
    return platformRouteError(error, 'Skill 详情暂时不可用。');
  }
}
