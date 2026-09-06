import PageContainer from '@/components/layout/page-container';
import {
  listWorkflowBatches,
  listWorkflowReusableFiles,
  listWorkflowSessions,
  listWorkflowSkills
} from '@/features/workflow-agent/api/server';
import { WorkflowLauncher } from '@/features/workflow-agent/components/workflow-launcher';

export const metadata = {
  title: '创建应收核销任务'
};

type PageProps = {
  searchParams: Promise<{ skill?: string | string[]; date?: string | string[] }>;
};

export default async function Page({ searchParams }: PageProps): Promise<React.JSX.Element> {
  const startedAt = performance.now();
  const params = await searchParams;
  const initialSkillId = typeof params.skill === 'string' ? params.skill : '';
  const initialDates = Array.isArray(params.date) ? params.date : params.date ? [params.date] : [];
  const [skills, workflows, batches] = await Promise.all([
    listWorkflowSkills(),
    listWorkflowSessions(),
    listWorkflowBatches()
  ]);
  console.info(
    `[dashboard-workflows-timing] catalog+recent ${Math.round(performance.now() - startedAt)}ms`
  );
  const selectedSkillId =
    initialSkillId && skills.some((skill) => skill.id === initialSkillId)
      ? initialSkillId
      : (skills[0]?.id ?? '');
  const initialReusableFiles = selectedSkillId
    ? await listWorkflowReusableFiles(selectedSkillId)
    : null;
  console.info(
    `[dashboard-workflows-timing] reusable-files ${Math.round(performance.now() - startedAt)}ms`
  );
  return (
    <PageContainer pageTitle='创建应收核销任务'>
      <WorkflowLauncher
        skills={skills}
        workflows={workflows}
        batches={batches}
        initialSkillId={selectedSkillId}
        initialDates={initialDates}
        initialReusableFiles={initialReusableFiles}
      />
    </PageContainer>
  );
}
