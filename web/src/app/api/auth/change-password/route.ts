import { proxyAuthRequest } from '@/features/auth/backend-proxy';

export function POST(request: Request) {
  return proxyAuthRequest(request, '/api/auth/change-password');
}
