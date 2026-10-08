import PageContainer from '@/components/layout/page-container';
import {PiChat} from '@/features/pi-runtime/pi-chat';
import type {PiSession} from '@/features/pi-runtime/pi-workspace';
import {platformServerRequest} from '@/features/platform-api/server-client';
import type {PlatformSession} from '@/features/platform-api/types';
import {getAssistantStatus, getAdminAssistantProfile, listAdminModelConnections} from '@/features/ai-chat/api/server';
import {AssistantDefaultModel} from '@/features/ai-chat/components/assistant-default-model';

export const metadata = {title: 'AI 助手'};

export default async function Page({searchParams}: {searchParams: Promise<{session?: string}>}) {
  const query = await searchParams;
  const [sessions, session, status] = await Promise.all([
    platformServerRequest<PiSession[]>('/api/pi-runtime/sessions'),
    platformServerRequest<PlatformSession>('/api/session'),
    getAssistantStatus()
  ]);
  const isAdmin = session.role === 'skill_admin';
  const storageScope = `${session.user_id}:${session.department_id}`;
  const [profile, connections] = isAdmin
    ? await Promise.all([getAdminAssistantProfile(), listAdminModelConnections()])
    : [undefined, []];
  return <PageContainer compact>
    <PiChat key={storageScope} storageScope={storageScope} initialSessions={sessions.filter(item => !item.skill_id)}
      initialSessionId={query.session}
      modelSettings={<AssistantDefaultModel isAdmin={isAdmin} status={status} profile={profile} connections={connections}/>}/>
  </PageContainer>;
}
