/** The platform API is the only browser transport for a Pi environment. */
export async function piRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  signal?.throwIfAborted();
  const response = await fetch('/api/platform/pi-runtime' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
    signal
  });
  const value: unknown = await response.json();
  signal?.throwIfAborted();
  if (!response.ok) {
    const detail = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    throw new Error(typeof detail.detail === 'string' ? detail.detail :
      typeof detail.message === 'string' ? detail.message : 'Agent 请求失败');
  }
  return value as T;
}
