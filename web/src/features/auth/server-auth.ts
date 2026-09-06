import 'server-only';

import { auth } from '@clerk/nextjs/server';
import { cookies } from 'next/headers';
import { cache } from 'react';
import { PlatformApiError } from '@/features/platform-api/errors';
import { authMode } from './auth-mode';

const SESSION_COOKIE = process.env.FINANCIAL_SESSION_COOKIE?.trim() || 'financial_session';

export interface PlatformCredential {
  provider: 'session' | 'clerk';
  token: string;
  clerkUserId: string | null;
}

export const platformCredential = cache(
  async function platformCredential(): Promise<PlatformCredential> {
    const mode = authMode();
    if (mode === 'clerk' || mode === 'hybrid') {
      const clerk = await auth();
      if (clerk.isAuthenticated) {
        const token = await clerk.getToken();
        if (!token) throw new PlatformApiError(401, '无法获取当前登录凭据，请重新登录。');
        return { provider: 'clerk', token, clerkUserId: clerk.userId };
      }
      if (mode === 'clerk') throw new PlatformApiError(401, '请先登录。');
    }

    const token = (await cookies()).get(SESSION_COOKIE)?.value ?? '';
    if (!token) throw new PlatformApiError(401, '请先登录。');
    return { provider: 'session', token, clerkUserId: null };
  }
);

export function credentialHeaders(credential: PlatformCredential): HeadersInit {
  return credential.provider === 'clerk'
    ? { Authorization: `Bearer ${credential.token}` }
    : { Cookie: `${SESSION_COOKIE}=${credential.token}` };
}

export function runtimeAccessToken(credential: PlatformCredential): string {
  return credential.provider === 'clerk' ? credential.token : `local.${credential.token}`;
}
