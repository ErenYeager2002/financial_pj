import { NextResponse } from 'next/server';
import { createWorkflow, type WorkflowCreateInput } from '@/features/workflow-agent/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

interface WorkflowCreateBody {
  skill_id: string;
  model_connection_id: string;
  model?: string;
}

function requestInput(value: unknown): WorkflowCreateInput {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '工作流创建请求格式无效。');
  }
  const body = value as Partial<WorkflowCreateBody>;
  const skillId = typeof body.skill_id === 'string' ? body.skill_id.trim() : '';
  const connectionId =
    typeof body.model_connection_id === 'string' ? body.model_connection_id.trim() : '';
  const model = typeof body.model === 'string' ? body.model.trim() : undefined;
  if (!skillId || !connectionId || (model !== undefined && !model)) {
    throw new PlatformApiError(400, 'Skill、模型连接和模型名称必须完整。');
  }
  return {
    skill_id: skillId,
    model_connection_id: connectionId,
    ...(model ? { model } : {})
  };
}

export async function POST(request: Request): Promise<Response> {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '工作流创建请求不是有效的 JSON。');
    }
    return NextResponse.json(await createWorkflow(requestInput(body)), { status: 201 });
  } catch (error) {
    return platformRouteError(error, '工作流创建失败。');
  }
}
