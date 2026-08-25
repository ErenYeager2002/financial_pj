import { proxyAuthRequest } from '@/features/auth/backend-proxy';

export function GET(request: Request) {
  return proxyAuthRequest(request, '/api/auth/session');
}
