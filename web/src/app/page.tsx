import { redirect } from 'next/navigation';
import { getPlatformSession } from '@/features/auth/api/service';

export default async function Page() {
  try {
    const session = await getPlatformSession();
    redirect(session.must_change_password ? '/auth/change-password' : '/dashboard/overview');
  } catch (error) {
    if (error && typeof error === 'object' && 'digest' in error) throw error;
  }
  redirect('/auth/sign-in');
}
