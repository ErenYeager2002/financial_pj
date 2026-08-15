import { platformRouteError } from '@/features/platform-api/route-handler';
import { downloadRunOutput } from '@/features/runs/api/server';

type Params = { params: Promise<{ runId: string; fileId: string }> };

export async function GET(request: Request, { params }: Params) {
  try {
    const { runId, fileId } = await params;
    const { response, file } = await downloadRunOutput(runId, fileId, request.signal);
    const headers = new Headers();
    headers.set('Content-Type', response.headers.get('content-type') ?? 'application/octet-stream');
    headers.set(
      'Content-Disposition',
      `attachment; filename*=UTF-8''${encodeURIComponent(file.name)}`
    );
    headers.set('Cache-Control', 'private, no-store');
    const contentLength = response.headers.get('content-length');
    if (contentLength) headers.set('Content-Length', contentLength);
    return new Response(response.body, { status: 200, headers });
  } catch (error) {
    return platformRouteError(error, '结果文件下载失败。');
  }
}
