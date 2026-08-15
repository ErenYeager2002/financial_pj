import { Metadata } from 'next';
import { auth } from '@clerk/nextjs/server';
import { redirect } from 'next/navigation';
import SignInViewPage from '@/features/auth/components/sign-in-view';

export const metadata: Metadata = {
  title: '登录',
  description: '登录企业管理后台。'
};

export default async function Page() {
  const { userId } = await auth();

  if (userId) {
    redirect('/dashboard/overview');
  }

  return <SignInViewPage />;
}
