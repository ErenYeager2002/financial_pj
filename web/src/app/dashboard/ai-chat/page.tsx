import PageContainer from '@/components/layout/page-container';
import {
  getAssistantStatus,
  getAdminAssistantProfile,
  listAdminModelConnections
} from '@/features/ai-chat/api/server';
import { AssistantWorkspace } from '@/features/ai-chat/components/assistant-workspace';
import { listAllFiles } from '@/features/files/api/server';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';

export const metadata = {
  title: 'AI 助手'
};

export default async function Page() {
  const [status, filePage, session] = await Promise.all([
    getAssistantStatus(),
    listAllFiles('input'),
    platformServerRequest<PlatformSession>('/api/session')
  ]);
  const isAdmin = session.role === 'skill_admin';
  const [profile, connections] = isAdmin
    ? await Promise.all([getAdminAssistantProfile(), listAdminModelConnections()])
    : [undefined, undefined];
  return (
    <PageContainer
      pageTitle='AI 助手'
      pageDescription='用自然语言生成财务任务草稿，确认后才会创建任务'
    >
      <AssistantWorkspace
        initialConfigured={status.configured}
        files={filePage}
        isAdmin={isAdmin}
        profile={profile}
        connections={connections}
      />
    </PageContainer>
  );
}
