import { NextResponse } from 'next/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';

export async function GET() {
  try {
    return NextResponse.json(await platformServerRequest('/api/pi-runtime/sessions'));
  } catch (error) {
    return platformRouteError(error, 'Pi 运行环境请求失败。');
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    return NextResponse.json(await platformServerRequest('/api/pi-runtime/sessions', {
      method: 'POST', body: JSON.stringify(body)
    }));
  } catch (error) {
    return platformRouteError(error, 'Pi 运行环境请求失败。');
  }
}
