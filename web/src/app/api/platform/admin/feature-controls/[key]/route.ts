import { NextResponse } from 'next/server';
import { updateFeatureControl } from '@/features/admin/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function PUT(request: Request, { params }: { params: Promise<{ key: string }> }) {
  try {
    const body = (await request.json()) as { enabled?: unknown };
    if (typeof body.enabled !== 'boolean') {
      return NextResponse.json({ detail: '开关状态格式无效。' }, { status: 400 });
    }
    return NextResponse.json(await updateFeatureControl((await params).key, body.enabled));
  } catch (error) {
    return platformRouteError(error, '功能开关保存失败。');
  }
}
