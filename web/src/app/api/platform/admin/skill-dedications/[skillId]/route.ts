import { NextResponse } from 'next/server';
import { clearSkillDedication, setSkillDedication } from '@/features/admin/api/skill-dedications';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ skillId: string }> };

export async function PUT(request: Request, { params }: Params) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, 'Skill 专属员工请求不是有效的 JSON。');
    }
    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      throw new PlatformApiError(400, 'Skill 专属员工请求格式无效。');
    }
    const userId = 'user_id' in body && typeof body.user_id === 'string' ? body.user_id : '';
    if (!userId) throw new PlatformApiError(400, '必须提供员工标识。');
    return NextResponse.json(await setSkillDedication((await params).skillId, userId));
  } catch (error) {
    return platformRouteError(error, 'Skill 专属员工设置失败。');
  }
}

export async function DELETE(_request: Request, { params }: Params) {
  try {
    await clearSkillDedication((await params).skillId);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return platformRouteError(error, 'Skill 专属员工清除失败。');
  }
}
