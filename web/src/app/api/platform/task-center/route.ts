import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { TaskCenterPage } from '@/features/platform-api/types';

const ALLOWED_PARAMS = new Set([
  'page',
  'page_size',
  'query',
  'view_state',
  'item_type',
  'skill_id',
  'business_date_from',
  'business_date_to',
  'updated_from',
  'updated_to'
]);

export async function GET(request: Request): Promise<Response> {
  const incoming = new URL(request.url).searchParams;
  const outgoing = new URLSearchParams();
  for (const [name, value] of incoming) {
    if (ALLOWED_PARAMS.has(name)) outgoing.append(name, value.slice(0, 160));
  }
  try {
    return NextResponse.json(
      await platformServerRequest<TaskCenterPage>(`/api/task-center?${outgoing}`)
    );
  } catch (error) {
    return platformRouteError(error, '正式任务加载失败。');
  }
}
