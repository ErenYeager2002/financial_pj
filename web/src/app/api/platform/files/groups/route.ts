import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { listFileGroups } from '@/features/files/api/server';

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const kind = params.get('kind') ?? '';
    const query = params.get('query') ?? '';
    const latestOnlyParam = params.get('latest_only');
    if (!['', 'input', 'output'].includes(kind)) {
      throw new PlatformApiError(400, '文件类型无效。');
    }
    if (latestOnlyParam !== null && !['true', 'false'].includes(latestOnlyParam)) {
      throw new PlatformApiError(400, 'latest_only 必须是 true 或 false。');
    }
    return NextResponse.json(
      await listFileGroups({
        kind,
        query,
        latestOnly: latestOnlyParam !== 'false'
      })
    );
  } catch (error) {
    return platformRouteError(error, '文件分组加载失败。');
  }
}
