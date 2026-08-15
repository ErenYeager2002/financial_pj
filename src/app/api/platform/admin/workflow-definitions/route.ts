import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { listWorkflowDefinitions } from '@/features/skill-governance/api/server';

export async function GET(): Promise<NextResponse> {
  try {
    return NextResponse.json(await listWorkflowDefinitions());
  } catch (error) {
    return platformRouteError(error, '工作流定义加载失败。');
  }
}
