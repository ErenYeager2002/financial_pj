import { notFound } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { WorkflowAgentPanel } from '@/features/workflow-agent/components/workflow-agent-panel';
import type { WorkflowRead } from '@/features/platform-api/types';

export const metadata = {
  title: '后台任务'
};

interface PageProps {
  params: Promise<{ workflowId: string }>;
}

export default async function Page({ params }: PageProps): Promise<React.JSX.Element> {
  const { workflowId } = await params;
  try {
    const workflow = await platformServerRequest<WorkflowRead>(`/api/workflows/${workflowId}`);
    return (
      <PageContainer
        pageTitle='后台任务'
        pageDescription='查看后台 Worker 的实时步骤、产出和错误位置'
      >
        <WorkflowAgentPanel initialWorkflow={workflow} />
      </PageContainer>
    );
  } catch (error) {
    if (error instanceof PlatformApiError && error.status === 404) notFound();
    throw error;
  }
}
