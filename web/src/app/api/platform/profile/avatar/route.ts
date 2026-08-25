import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import {
  platformServerRequest,
  platformServerResponse
} from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { PlatformSession } from '@/features/platform-api/types';

export async function GET(): Promise<Response> {
  try {
    const response = await platformServerResponse('/api/profile/avatar');
    const headers = new Headers();
    for (const name of [
      'content-type',
      'content-length',
      'cache-control',
      'last-modified',
      'x-content-type-options'
    ]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(response.body, { status: 200, headers });
  } catch (error) {
    return platformRouteError(error, '头像读取失败。');
  }
}

export async function POST(request: Request): Promise<Response> {
  try {
    const incoming = await request.formData();
    const upload = incoming.get('upload');
    if (!(upload instanceof File)) {
      throw new PlatformApiError(400, '请选择头像图片。');
    }
    const form = new FormData();
    form.set('upload', upload);
    const session = await platformServerRequest<PlatformSession>('/api/profile/avatar', {
      method: 'POST',
      body: form
    });
    return NextResponse.json(session);
  } catch (error) {
    return platformRouteError(error, '头像上传失败。');
  }
}
