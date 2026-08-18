import PageContainer from '@/components/layout/page-container';
import { listWorkflowSessions, listWorkflowSkills } from '@/features/workflow-agent/api/server';
import { WorkflowLauncher } from '@/features/workflow-agent/components/workflow-launcher';

export const metadata = {
  title: '后台任务'
};

type PageProps = {
  searchParams: Promise<{ skill?: string | string[] }>;
};

export default async function Page({ searchParams }: PageProps): Promise<React.JSX.Element> {
  const params = await searchParams;
  const initialSkillId = typeof params.skill === 'string' ? params.skill : '';
  const [skills, workflows] = await Promise.all([listWorkflowSkills(), listWorkflowSessions()]);
  return (
    <PageContainer
      pageTitle='后台任务'
      pageDescription='选择日期和材料后提交后台任务，状态由 Worker 持续更新'
    >
      <WorkflowLauncher skills={skills} workflows={workflows} initialSkillId={initialSkillId} />
    </PageContainer>
  );
}
