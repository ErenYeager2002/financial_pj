import ProfileViewPage from '@/features/profile/components/profile-view-page';
import { getPlatformSession } from '@/features/auth/api/service';

export const metadata = {
  title: '个人资料'
};

export default async function Page() {
  return <ProfileViewPage session={await getPlatformSession()} />;
}
