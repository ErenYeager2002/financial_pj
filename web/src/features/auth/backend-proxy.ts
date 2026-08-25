import 'server-only';

import { platformServerBaseUrl } from '@/features/platform-api/server-client';

const ALLOWED_PATHS = new Set([
  '/api/auth/login',
  '/api/auth/logout',
  '/api/auth/change-password',
  '/api/auth/session'
]);

export async function proxyAuthRequest(request: Request, path: string): Promise<Response> {
  if (!ALLOWED_PATHS.has(path)) return new Response(null, { status: 404 });
  const headers = new Headers();
  for (const name of ['content-type', 'cookie', 'origin', 'user-agent']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const upstream = await fetch(`${platformServerBaseUrl()}${path}`, {
    method: request.method,
    headers,
    body: request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.text(),
    cache: 'no-store',
    redirect: 'manual'
  });
  const responseHeaders = new Headers();
  const contentType = upstream.headers.get('content-type');
  if (contentType) responseHeaders.set('content-type', contentType);
  const getSetCookie = (upstream.headers as Headers & { getSetCookie?: () => string[] })
    .getSetCookie;
  const cookies = getSetCookie ? getSetCookie.call(upstream.headers) : [];
  if (cookies.length) {
    for (const cookie of cookies) responseHeaders.append('set-cookie', cookie);
  } else {
    const cookie = upstream.headers.get('set-cookie');
    if (cookie) responseHeaders.append('set-cookie', cookie);
  }
  const body = upstream.status === 204 || upstream.status === 304 ? null : await upstream.arrayBuffer();
  return new Response(body, {
    status: upstream.status,
    headers: responseHeaders
  });
}
