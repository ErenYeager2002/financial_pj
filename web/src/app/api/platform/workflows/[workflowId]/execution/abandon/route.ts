import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Context = { params: Promise<{ workflowId: string }> };
async function endpoint(context: Context): Promise<string> {
  const { workflowId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
  return `/api/workflows/${workflowId}/execution/abandon`;
}
export async function GET(_request: Request, context: Context): Promise<Response> {
  try { return NextResponse.json(await platformServerRequest(await endpoint(context))); }
  catch (error) { return platformRouteError(error, '读取放弃条件失败。'); }
}
export async function POST(request: Request, context: Context): Promise<Response> {
  try {
    const raw: unknown = await request.json();
    if (!raw || typeof raw !== 'object' || !('checkpoint_fingerprint' in raw)
      || typeof raw.checkpoint_fingerprint !== 'string' || !/^[0-9a-f]{64}$/.test(raw.checkpoint_fingerprint)) {
      throw new PlatformApiError(400, '检查点无效，请刷新后重试。');
    }
    return NextResponse.json(await platformServerRequest(await endpoint(context), {
      method: 'POST', body: JSON.stringify({ checkpoint_fingerprint: raw.checkpoint_fingerprint })
    }));
  } catch (error) { return platformRouteError(error, '放弃未发布结果失败。'); }
}
