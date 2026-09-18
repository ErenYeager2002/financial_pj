import PageContainer from '@/components/layout/page-container';
import { PiWorkspace, type PiSession } from '@/features/pi-runtime/pi-workspace';
import { platformServerRequest } from '@/features/platform-api/server-client';

export const metadata = { title: 'Pi 工作区' };

export default async function Page({ searchParams }: { searchParams: Promise<{ session?: string }> }) {
  const [sessions, query] = await Promise.all([
    platformServerRequest<PiSession[]>('/api/pi-runtime/sessions'), searchParams
  ]);
  return <PageContainer pageTitle='Pi 工作区' headingLevel={1} compact>
    <PiWorkspace initialSessions={sessions.filter(item=>item.channel==='workspace')} initialSessionId={query.session} />
  </PageContainer>;
}
