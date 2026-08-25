import { NextResponse } from 'next/server';
import {
  confirmSkillSourceBinding,
  listSkillSourceBindings
} from '@/features/admin/api/skill-releases';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listSkillSourceBindings());
  } catch (error) {
    return platformRouteError(error, 'Skill 源码绑定读取失败。');
  }
}

export async function POST(request: Request) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '源码绑定请求不是有效的 JSON。');
    }
    return NextResponse.json(await confirmSkillSourceBinding(body), { status: 201 });
  } catch (error) {
    return platformRouteError(error, 'Skill 源码绑定失败。');
  }
}
