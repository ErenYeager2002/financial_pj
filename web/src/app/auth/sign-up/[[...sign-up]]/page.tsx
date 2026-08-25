import { Metadata } from 'next';
import SignUpViewPage from '@/features/auth/components/sign-up-view';
import { authMode } from '@/features/auth/auth-mode';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: '注册',
  description: '创建企业管理后台账号。'
};

export default function Page() {
  if (authMode() === 'session') redirect('/auth/sign-in');
  return <SignUpViewPage />;
}
