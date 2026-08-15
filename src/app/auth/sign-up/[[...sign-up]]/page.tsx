import { Metadata } from 'next';
import SignUpViewPage from '@/features/auth/components/sign-up-view';

export const metadata: Metadata = {
  title: '注册',
  description: '创建企业管理后台账号。'
};

export default function Page() {
  return <SignUpViewPage />;
}
