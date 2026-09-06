import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { listFiles } from '@/features/files/api/server';
import { uploadFileForSkill } from '@/features/run-setup/api/server';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const page = Number(params.get('page') ?? '1');
    const pageSize = Number(params.get('page_size') ?? '25');
    const kind = params.get('kind') ?? '';
    const query = params.get('query') ?? '';
    const skillId = (params.get('skill_id') ?? '').trim();
    const unassignedParam = params.get('unassigned');
    const includeDeleteStatusParam = params.get('include_delete_status');
    if (!Number.isSafeInteger(page) || page < 1) {
      throw new PlatformApiError(400, '页码必须是正整数。');
    }
    if (!Number.isSafeInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new PlatformApiError(400, '每页数量必须是 1 到 100 之间的整数。');
    }
    if (!['', 'input', 'output'].includes(kind)) {
      throw new PlatformApiError(400, '文件类型无效。');
    }
    if (skillId.length > 128) {
      throw new PlatformApiError(400, 'Skill 标识格式无效。');
    }
    if (unassignedParam !== null && !['true', 'false'].includes(unassignedParam)) {
      throw new PlatformApiError(400, 'unassigned 必须是 true 或 false。');
    }
    if (skillId && unassignedParam === 'true') {
      throw new PlatformApiError(400, 'skill_id 和 unassigned 不能同时使用。');
    }
    if (
      includeDeleteStatusParam !== null &&
      !['true', 'false'].includes(includeDeleteStatusParam)
    ) {
      throw new PlatformApiError(400, 'include_delete_status 必须是 true 或 false。');
    }
    return NextResponse.json(
      await listFiles({
        page,
        pageSize,
        kind,
        query,
        includeDeleteStatus: includeDeleteStatusParam !== 'false',
        skillId,
        unassigned: unassignedParam === 'true'
      })
    );
  } catch (error) {
    return platformRouteError(error, '文件列表加载失败。');
  }
}

export async function POST(request: Request) {
  try {
    const form = await request.formData();
    const skillId = form.get('skill_id');
    const role = form.get('role');
    const workflowId = form.get('workflow_id');
    const workflowUpload = form.get('workflow_upload');
    const upload = form.get('upload');
    if (typeof skillId !== 'string' || typeof role !== 'string' || !(upload instanceof File)) {
      throw new PlatformApiError(400, '上传请求缺少 Skill、文件用途或文件。');
    }
    if (workflowId !== null && (typeof workflowId !== 'string' || !UUID.test(workflowId))) {
      throw new PlatformApiError(400, '工作流标识格式无效。');
    }
    return NextResponse.json(
      await uploadFileForSkill(
        skillId,
        role,
        upload,
        (typeof workflowId === 'string' && workflowId.length > 0) || workflowUpload === 'true'
      )
    );
  } catch (error) {
    return platformRouteError(error, '文件上传失败。');
  }
}
