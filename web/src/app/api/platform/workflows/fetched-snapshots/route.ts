import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowFetchedSnapshot } from '@/features/platform-api/types';

const ID = /^[A-Za-z0-9._-]+$/;

export async function GET(request: Request): Promise<Response> {
  try {
    const skillId = new URL(request.url).searchParams.get('skill_id')?.trim() ?? '';
    if (!ID.test(skillId)) throw new PlatformApiError(400, 'Skill 标识格式无效。');
    const snapshots = await platformServerRequest<WorkflowFetchedSnapshot[]>(
      `/api/workflows/fetched-snapshots?skill_id=${encodeURIComponent(skillId)}`
    );
    return NextResponse.json(snapshots);
  } catch (error) {
    return platformRouteError(error, '取数记录加载失败。');
  }
}
