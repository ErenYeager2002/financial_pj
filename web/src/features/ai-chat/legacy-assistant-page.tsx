import PageContainer from '@/components/layout/page-container';
import {
  getAssistantStatus,
  getAdminAssistantProfile,
  listAdminModelConnections
} from '@/features/ai-chat/api/server';
import { AssistantWorkspace } from '@/features/ai-chat/components/assistant-workspace';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';

export const metadata = {
  title: 'AI 助手'
};

export default async function Page() {
  const [status, session] = await Promise.all([
    getAssistantStatus(),
    platformServerRequest<PlatformSession>('/api/session')
  ]);
  const isAdmin = session.role === 'skill_admin';
  const [profile, connections] = isAdmin
    ? await Promise.all([getAdminAssistantProfile(), listAdminModelConnections()])
    : [undefined, undefined];
  return (
    <PageContainer
      pageTitle='AI 助手' headingLevel={1} compact
    >
      <AssistantWorkspace
        initialConfigured={status.configured}
        initialModel={status.model}
        isAdmin={isAdmin}
        profile={profile}
        connections={connections}
      />
    </PageContainer>
  );
}
