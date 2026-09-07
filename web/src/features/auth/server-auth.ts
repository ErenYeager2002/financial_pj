import 'server-only';
import { cookies } from 'next/headers';
import { cache } from 'react';
import { PlatformApiError } from '@/features/platform-api/errors';

const SESSION_COOKIE = process.env.FINANCIAL_SESSION_COOKIE?.trim() || 'financial_session';
export interface PlatformCredential {
  provider: 'session';
  token: string;
  clerkUserId: null;
}
export const platformCredential = cache(async function platformCredential(): Promise<PlatformCredential> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value ?? '';
  if (!token) throw new PlatformApiError(401, '请先登录。');
  return { provider: 'session', token, clerkUserId: null };
});
export function credentialHeaders(credential: PlatformCredential): HeadersInit {
  return { Cookie: `${SESSION_COOKIE}=${credential.token}` };
}
export function runtimeAccessToken(credential: PlatformCredential): string {
  return `local.${credential.token}`;
}
