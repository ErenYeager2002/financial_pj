import PageContainer from '@/components/layout/page-container';
import { redirect } from 'next/navigation';
import { getTaskReminderBoard } from '@/features/task-reminders/api/server';
import { getTaskCenterPage, hasAnyFormalTask } from '@/features/task-center/api/server';
import {
  FormalTaskRegion,
  TaskReminderRegion
} from '@/features/task-center/components/task-center-regions';
import {
  hasTaskCenterFilters,
  parseTaskCenterQuery,
  taskCenterPageRedirect,
  type TaskCenterRawQuery
} from '@/features/task-center/query';
import { settleRegionLoad } from '@/features/task-center/region-load';

export const metadata = {
  title: '我的任务'
};

type PageProps = {
  searchParams: Promise<TaskCenterRawQuery>;
};

export default async function Page({ searchParams }: PageProps) {
  const query = parseTaskCenterQuery(await searchParams);
  const [formalTasks, reminders] = await Promise.all([
    settleRegionLoad(async () => {
      const page = await getTaskCenterPage(query);
      const hasAnyTasks =
        page.total > 0 || (hasTaskCenterFilters(query) ? await hasAnyFormalTask() : false);
      return { page, hasAnyTasks };
    }),
    settleRegionLoad(getTaskReminderBoard)
  ]);
  if (formalTasks.state === 'ready') {
    const canonicalHref = taskCenterPageRedirect(query, formalTasks.data.page.pages);
    if (canonicalHref) redirect(canonicalHref);
  }

  return (
    <PageContainer pageTitle='我的任务' headingLevel={1}>
      <div className='space-y-6'>
        <TaskReminderRegion initial={reminders} />
        <FormalTaskRegion initial={formalTasks} query={query} />
      </div>
    </PageContainer>
  );
}
