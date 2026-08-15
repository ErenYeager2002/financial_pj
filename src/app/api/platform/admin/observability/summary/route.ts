import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { getObservabilitySummary } from '@/features/skill-governance/api/server';

function observabilityHours(request: Request): number {
  const value = Number(new URL(request.url).searchParams.get('hours') ?? '24');
  return Number.isSafeInteger(value) ? value : 24;
}

export async function GET(request: Request): Promise<NextResponse> {
  try {
    return NextResponse.json(await getObservabilitySummary(observabilityHours(request)));
  } catch (error) {
    return platformRouteError(error, '运行观测数据加载失败。');
  }
}
