import { NextResponse } from 'next/server';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { getSubmissionReceipt } from '@/features/run-setup/api/server';

type Params = { params: Promise<{ requestId: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const { requestId } = await params;
    return NextResponse.json(await getSubmissionReceipt(requestId));
  } catch (error) {
    return platformRouteError(error, '提交状态加载失败。');
  }
}
