import { notFound, redirect } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { WorkflowAgentPanel } from '@/features/workflow-agent/components/workflow-agent-panel';
import type { WorkflowRead } from '@/features/platform-api/types';

export const metadata = {
  title: '应收核销任务详情'
};

interface PageProps {
  params: Promise<{ workflowId: string }>;
}

export default async function Page({ params }: PageProps): Promise<React.JSX.Element> {
  const { workflowId } = await params;
  try {
    const workflow = await platformServerRequest<WorkflowRead>(`/api/workflows/${workflowId}`);
    if (workflow.batch_id) {
      redirect(`/dashboard/workflows/batches/${encodeURIComponent(workflow.batch_id)}`);
    }
    return (
      <PageContainer pageTitle='应收核销任务详情'>
        <WorkflowAgentPanel initialWorkflow={workflow} />
      </PageContainer>
    );
  } catch (error) {
    if (error instanceof PlatformApiError && error.status === 404) notFound();
    throw error;
  }
}
