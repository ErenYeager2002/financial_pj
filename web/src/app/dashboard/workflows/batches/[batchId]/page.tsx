import { notFound } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { WorkflowBatchProgress } from '@/features/workflow-agent/components/workflow-batch-progress';
import type { WorkflowBatchRead } from '@/features/platform-api/types';

export const metadata = {
  title: '应收核销批次详情'
};

interface PageProps {
  params: Promise<{ batchId: string }>;
}

export default async function Page({ params }: PageProps): Promise<React.JSX.Element> {
  const { batchId } = await params;
  try {
    const batch = await platformServerRequest<WorkflowBatchRead>(
      `/api/workflow-batches/${batchId}`
    );
    return (
      <PageContainer
        pageTitle='应收核销批次详情'
        pageDescription='按日期顺序执行并持续显示每一天的处理步骤'
      >
        <WorkflowBatchProgress initialBatch={batch} />
      </PageContainer>
    );
  } catch (error) {
    if (error instanceof PlatformApiError && error.status === 404) notFound();
    throw error;
  }
}
