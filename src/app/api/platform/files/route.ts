import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { listFiles } from '@/features/files/api/server';
import { uploadFileForSkill } from '@/features/run-setup/api/server';

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const page = Number(params.get('page') ?? '1');
    const pageSize = Number(params.get('page_size') ?? '20');
    const kind = params.get('kind') ?? '';
    const query = params.get('query') ?? '';
    if (!Number.isSafeInteger(page) || page < 1) {
      throw new PlatformApiError(400, '页码必须是正整数。');
    }
    if (!Number.isSafeInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new PlatformApiError(400, '每页数量必须是 1 到 100 之间的整数。');
    }
    if (!['', 'input', 'output'].includes(kind)) {
      throw new PlatformApiError(400, '文件类型无效。');
    }
    return NextResponse.json(await listFiles(page, pageSize, kind, query));
  } catch (error) {
    return platformRouteError(error, '文件列表加载失败。');
  }
}

export async function POST(request: Request) {
  try {
    const form = await request.formData();
    const skillId = form.get('skill_id');
    const role = form.get('role');
    const upload = form.get('upload');
    if (typeof skillId !== 'string' || typeof role !== 'string' || !(upload instanceof File)) {
      throw new PlatformApiError(400, '上传请求缺少 Skill、文件用途或文件。');
    }
    return NextResponse.json(await uploadFileForSkill(skillId, role, upload));
  } catch (error) {
    return platformRouteError(error, '文件上传失败。');
  }
}
