import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { platformServerRequest } from '@/features/platform-api/server-client';

export async function GET(request: Request): Promise<Response> {
  try {
    const skillId = new URL(request.url).searchParams.get('skill_id')?.trim() ?? '';
    if (!/^[A-Za-z0-9._-]+$/.test(skillId)) throw new PlatformApiError(400, 'Skill 标识格式无效。');
    const state = await platformServerRequest<{ locked: boolean; reason: string }>(
      `/api/workflows/material-edit-state?skill_id=${encodeURIComponent(skillId)}`
    );
    return NextResponse.json(state, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return platformRouteError(error, '材料编辑状态读取失败。');
  }
}
