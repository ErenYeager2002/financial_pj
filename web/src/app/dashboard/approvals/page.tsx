import { redirect } from 'next/navigation';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';

export const metadata = { title: '后台任务' };

export default async function ApprovalsPage() {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role === 'skill_admin' || session.role === 'finance_user') {
    redirect('/dashboard/workflows');
  }
  redirect('/dashboard/overview');
}
