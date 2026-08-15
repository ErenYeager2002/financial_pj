import { NextResponse } from 'next/server';
import { decideApproval } from '@/features/admin/api/approvals';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function POST(request: Request, context: { params: Promise<{ approvalId: string }> }) {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '审批请求不是有效的 JSON。');
    }
    const { approvalId } = await context.params;
    return NextResponse.json(await decideApproval(approvalId, body));
  } catch (error) {
    return platformRouteError(error, '审批决定提交失败。');
  }
}
