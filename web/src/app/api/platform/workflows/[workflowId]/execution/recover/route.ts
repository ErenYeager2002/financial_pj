import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { ArExecutionRead, ArRecoveryRequest } from '@/features/platform-api/generated';

export async function POST(request: Request, { params }: { params: Promise<{ workflowId: string }> }): Promise<Response> {
  try {
    const { workflowId } = await params;
    if (!/^[0-9a-f-]{36}$/i.test(workflowId)) throw new PlatformApiError(400, '工作流标识格式无效。');
    const raw: unknown = await request.json();
    if (!raw || typeof raw !== 'object' || !('failed_action_id' in raw) || !('checkpoint_fingerprint' in raw)
      || typeof raw.failed_action_id !== 'string' || typeof raw.checkpoint_fingerprint !== 'string') {
      throw new PlatformApiError(400, '恢复请求缺少原失败动作或检查点。');
    }
    const body: ArRecoveryRequest = { failed_action_id: raw.failed_action_id, checkpoint_fingerprint: raw.checkpoint_fingerprint };
    return NextResponse.json(await platformServerRequest<ArExecutionRead>(`/api/workflows/${workflowId}/execution/recover`, {
      method: 'POST', body: JSON.stringify(body)
    }));
  } catch (error) {
    return platformRouteError(error, '恢复未完成阶段失败。');
  }
}
