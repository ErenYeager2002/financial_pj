import { platformServerRequest } from '@/features/platform-api/server-client';
import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { listWorkflowReusableFiles } from '@/features/workflow-agent/api/server';

const ID = /^[A-Za-z0-9._-]+$/;

export async function GET(request: Request): Promise<Response> {
  try {
    const skillId = new URL(request.url).searchParams.get('skill_id')?.trim() ?? '';
    if (!ID.test(skillId)) {
      throw new PlatformApiError(400, 'Skill 标识格式无效。');
    }
    const page = Number(new URL(request.url).searchParams.get('candidate_page') ?? '1');
    if (!Number.isSafeInteger(page) || page < 1) throw new PlatformApiError(400, '候选文件页码无效。');
    return NextResponse.json(await listWorkflowReusableFiles(skillId, page));
  } catch (error) {
    return platformRouteError(error, '已保存任务材料加载失败。');
  }
}

export async function DELETE(request: Request): Promise<Response> {
  try {
    const params = new URL(request.url).searchParams;
    const skillId = params.get('skill_id') ?? '';
    const fileId = params.get('file_id');
    const allFiles = params.get('all_files') === 'true';
    if (!ID.test(skillId) || (fileId !== null && !ID.test(fileId)) || Boolean(fileId) === allFiles) {
      throw new PlatformApiError(400, '移除候选文件的请求无效。');
    }
    const query = new URLSearchParams({ skill_id: skillId });
    if (fileId) query.set('file_id', fileId);
    if (allFiles) query.set('all_files', 'true');
    return NextResponse.json(await platformServerRequest(`/api/workflows/reusable-files?${query}`, { method: 'DELETE' }));
  } catch (error) {
    return platformRouteError(error, '候选文件移除失败。');
  }
}
