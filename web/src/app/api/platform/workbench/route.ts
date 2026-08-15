import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { getWorkbench } from '@/features/workbench/api/server';

export async function GET() {
  try {
    return NextResponse.json(await getWorkbench());
  } catch (error) {
    return platformRouteError(error, '工作台加载失败。');
  }
}
