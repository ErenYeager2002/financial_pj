import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { ServiceCredentialRead } from '@/features/platform-api/types';

interface Params {
  params: Promise<{ service: string }>;
}

function checkedService(value: string): string {
  if (!['zhiyun', 'kingdee'].includes(value)) {
    throw new PlatformApiError(404, '不支持的业务系统凭据。');
  }
  return value;
}

function credentialInput(value: unknown): { account: string; password: string } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '凭据请求格式无效。');
  }
  const body = value as Record<string, unknown>;
  const account = typeof body.account === 'string' ? body.account.trim() : '';
  const password = typeof body.password === 'string' ? body.password : '';
  if (!account || !password) {
    throw new PlatformApiError(422, '账号和密码不能为空。');
  }
  if (account.length > 255 || password.length > 512) {
    throw new PlatformApiError(422, '账号或密码长度超出允许范围。');
  }
  return { account, password };
}

export async function GET(_request: Request, { params }: Params): Promise<Response> {
  try {
    const service = checkedService((await params).service);
    return NextResponse.json(
      await platformServerRequest<ServiceCredentialRead>(`/api/service-credentials/${service}`)
    );
  } catch (error) {
    return platformRouteError(error, '业务系统登录凭据状态加载失败。');
  }
}

export async function PUT(request: Request, { params }: Params): Promise<Response> {
  try {
    const service = checkedService((await params).service);
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '凭据请求不是有效的 JSON。');
    }
    return NextResponse.json(
      await platformServerRequest<ServiceCredentialRead>(`/api/service-credentials/${service}`, {
        method: 'PUT',
        body: JSON.stringify(credentialInput(body))
      })
    );
  } catch (error) {
    return platformRouteError(error, '业务系统登录凭据保存失败。');
  }
}
