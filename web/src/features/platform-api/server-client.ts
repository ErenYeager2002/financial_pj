import 'server-only';

import { credentialHeaders, platformCredential } from '@/features/auth/server-auth';
import { PlatformApiError, platformErrorMessage } from './errors';

const DEFAULT_TIMEOUT_MS = 30_000;

interface PlatformRequestOptions {
  timeoutMs?: number | null;
}

export function platformServerBaseUrl(): string {
  const value = process.env.FINANCIAL_PLATFORM_API_URL?.trim();
  if (!value) {
    throw new PlatformApiError(500, '财务平台 API 地址尚未配置。');
  }
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new PlatformApiError(500, '财务平台 API 地址配置无效。');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new PlatformApiError(500, '财务平台 API 地址协议不受支持。');
  }
  return parsed.toString().replace(/\/$/, '');
}

function platformPath(path: string): string {
  const pathname = path.split(/[?#]/, 1)[0];
  if (
    !path.startsWith('/api/') ||
    path.includes('://') ||
    path.includes('\\') ||
    pathname.split('/').includes('..')
  ) {
    throw new PlatformApiError(500, '财务平台 API 路径不受允许。');
  }
  return path;
}

async function responseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function platformServerResponse(
  path: string,
  init: RequestInit = {},
  options: PlatformRequestOptions = {}
): Promise<Response> {
  const headers = new Headers(init.headers);
  const credential = await platformCredential();
  for (const [name, value] of Object.entries(credentialHeaders(credential))) {
    headers.set(name, String(value));
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const configuredTimeout = Number(process.env.FINANCIAL_PLATFORM_REQUEST_TIMEOUT_MS);
  const defaultTimeout =
    Number.isFinite(configuredTimeout) && configuredTimeout > 0
      ? configuredTimeout
      : DEFAULT_TIMEOUT_MS;
  const timeoutMs = options.timeoutMs === undefined ? defaultTimeout : options.timeoutMs;
  const response = await fetch(`${platformServerBaseUrl()}${platformPath(path)}`, {
    ...init,
    headers,
    cache: 'no-store',
    signal: init.signal ?? (timeoutMs === null ? undefined : AbortSignal.timeout(timeoutMs))
  });
  if (!response.ok) {
    const body = await responseBody(response);
    throw new PlatformApiError(
      response.status,
      platformErrorMessage(body, `财务平台请求失败（${response.status}）。`)
    );
  }
  return response;
}

export async function platformServerRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await platformServerResponse(path, init);
  const body = await responseBody(response);
  return body as T;
}
