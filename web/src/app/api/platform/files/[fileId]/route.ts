import { NextResponse } from 'next/server';
import { deleteFile, getFile } from '@/features/files/api/server';
import { platformRouteError } from '@/features/platform-api/route-handler';

type Params = { params: Promise<{ fileId: string }> };

export async function GET(_request: Request, { params }: Params) {
  try {
    const { fileId } = await params;
    return NextResponse.json(await getFile(fileId));
  } catch (error) {
    return platformRouteError(error, '文件详情加载失败。');
  }
}

export async function DELETE(_request: Request, { params }: Params) {
  try {
    const { fileId } = await params;
    await deleteFile(fileId);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return platformRouteError(error, '文件删除失败。');
  }
}
