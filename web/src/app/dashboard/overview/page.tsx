import PageContainer from '@/components/layout/page-container';
import { getPlatformHealth, getWorkbench } from '@/features/workbench/api/server';
import { WorkbenchOverview } from '@/features/workbench/components/workbench-overview';

export default async function OverviewPage() {
  const [workbench, health] = await Promise.all([getWorkbench(), getPlatformHealth()]);
  return (
    <PageContainer compact>
      <WorkbenchOverview data={workbench} health={health} />
    </PageContainer>
  );
}
