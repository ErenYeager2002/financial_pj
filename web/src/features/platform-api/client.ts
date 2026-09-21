import { platformApiError } from './errors';

export async function platformClientRequest<T>(
  path: string,
  fallback: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...init });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Use the bounded fallback for non-JSON responses.
    }
    throw platformApiError(response.status, body, fallback);
  }
  return (await response.json()) as T;
}
