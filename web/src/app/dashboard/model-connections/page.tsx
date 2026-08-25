import PageContainer from '@/components/layout/page-container';
import {
  listAdminModelConnections,
  listAdminModelProviders
} from '@/features/model-connections/api/server';
import { ModelConnectionManagement } from '@/features/model-connections/components/model-connection-management';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';

export const metadata = { title: '模型连接' };

export default async function ModelConnectionsPage(): Promise<React.JSX.Element> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    return (
      <PageContainer
        access={false}
        accessFallback={<p className='text-muted-foreground'>只有平台管理员可以管理模型连接。</p>}
      >
        {null}
      </PageContainer>
    );
  }
  const [connections, providers] = await Promise.all([
    listAdminModelConnections(),
    listAdminModelProviders()
  ]);
  return (
    <PageContainer
      pageTitle='模型连接'
      pageDescription='集中管理 AI 助手使用的模型供应商、API Key 和可用模型'
    >
      <ModelConnectionManagement initialConnections={connections} providers={providers} />
    </PageContainer>
  );
}
