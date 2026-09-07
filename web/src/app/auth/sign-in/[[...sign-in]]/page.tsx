import { Metadata } from 'next';
import { redirect } from 'next/navigation';
import SignInViewPage from '@/features/auth/components/sign-in-view';
import { authMode } from '@/features/auth/auth-mode';
import { getPlatformSession } from '@/features/auth/api/service';

export const metadata: Metadata = {
  title: '登录',
  description: '登录财务自动化平台。'
};

export default async function Page() {
  let session = null;
  try {
    session = await getPlatformSession();
  } catch {
    // 未登录时显示对应模式的登录表单。
  }
  if (session) {
    redirect(session.must_change_password ? '/auth/change-password' : '/dashboard/overview');
  }
  return <SignInViewPage mode={authMode()} />;
}
