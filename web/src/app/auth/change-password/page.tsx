import ChangePasswordForm from '@/features/auth/components/change-password-form';
import { getPlatformSession } from '@/features/auth/api/service';
import { redirect } from 'next/navigation';

export default async function ChangePasswordPage() {
  let session;
  try {
    session = await getPlatformSession();
  } catch {
    redirect('/auth/sign-in');
  }
  return <main className='flex min-h-screen items-center justify-center p-4'><ChangePasswordForm mustChangePassword={session.must_change_password} /></main>;
}
