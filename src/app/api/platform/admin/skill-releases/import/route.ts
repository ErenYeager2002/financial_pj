import { NextResponse } from 'next/server';
import { importSkillRelease } from '@/features/admin/api/skill-releases';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(request: Request) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '导入请求不是有效的 JSON。');
    }
    return NextResponse.json(await importSkillRelease(body), { status: 201 });
  } catch (error) {
    return platformRouteError(error, 'Skill 发布包导入失败。');
  }
}
