import { NextResponse } from 'next/server';
import { listFeatureControls } from '@/features/admin/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await listFeatureControls());
  } catch (error) {
    return platformRouteError(error, '功能开关列表读取失败。');
  }
}
