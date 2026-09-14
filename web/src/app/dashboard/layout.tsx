import KBar from '@/components/kbar';
import AppSidebar from '@/components/layout/app-sidebar';
import Header from '@/components/layout/header';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { getNavGroups } from '@/config/nav-config';
import { getPlatformSession } from '@/features/auth/api/service';
import type { Metadata } from 'next';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

export const metadata: Metadata = {
  title: { absolute: '财务自动化平台' },
  description: '财务 Skill 执行、任务和治理平台',
  robots: {
    index: false,
    follow: false
  }
};

export default async function DashboardLayout({
  children
}: {
  children: React.ReactNode;
}): Promise<React.JSX.Element> {
  const cookieStore = await cookies();
  let session;
  try {
    session = await getPlatformSession();
  } catch {
    redirect('/auth/sign-in');
  }
  if (session.must_change_password) redirect('/auth/change-password');
  const defaultOpen = cookieStore.get('sidebar_state')?.value !== 'false';
  const navGroups = getNavGroups(session.role);
  return (
    <KBar navGroups={navGroups}>
      <SidebarProvider defaultOpen={defaultOpen}>
        <a
          href='#main-content'
          className='bg-background ring-ring sr-only rounded-md px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:absolute focus:top-2 focus:start-2 focus:z-50 focus:ring-2'
        >
          跳到主要内容
        </a>
        <AppSidebar navGroups={navGroups} session={session} />
        <SidebarInset id='main-content' tabIndex={-1} className='min-w-0 scroll-mt-16'>
          <Header />
          {children}
        </SidebarInset>
      </SidebarProvider>
    </KBar>
  );
}
