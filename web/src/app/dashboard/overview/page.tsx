import PageContainer from '@/components/layout/page-container';
import { getWorkbench } from '@/features/workbench/api/server';
import { WorkbenchOverview } from '@/features/workbench/components/workbench-overview';

export default async function OverviewPage() {
  const workbench = await getWorkbench();
  return (
    <PageContainer>
      <WorkbenchOverview data={workbench} />
    </PageContainer>
  );
}
