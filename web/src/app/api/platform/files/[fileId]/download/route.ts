import { downloadFile } from '@/features/files/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ fileId: string }> };

export async function GET(request: Request, { params }: Params) {
  try {
    const { fileId } = await params;
    const { response, file } = await downloadFile(fileId, request.signal);
    const headers = new Headers();
    headers.set('Content-Type', response.headers.get('content-type') ?? file.content_type);
    headers.set(
      'Content-Disposition',
      `attachment; filename*=UTF-8''${encodeURIComponent(file.name)}`
    );
    headers.set('Cache-Control', 'private, no-store');
    const contentLength = response.headers.get('content-length');
    if (contentLength) headers.set('Content-Length', contentLength);
    return new Response(response.body, { status: 200, headers });
  } catch (error) {
    return platformRouteError(error, '文件下载失败。');
  }
}
