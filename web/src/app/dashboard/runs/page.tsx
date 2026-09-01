import PageContainer from '@/components/layout/page-container';
import { redirect } from 'next/navigation';
import { getTaskReminderBoard } from '@/features/task-reminders/api/server';
import { getTaskCenterPage } from '@/features/task-center/api/server';
import {
  FormalTaskRegion,
  TaskReminderRegion
} from '@/features/task-center/components/task-center-regions';
import {
  hasTaskCenterUnsupportedParams,
  parseTaskCenterQuery,
  taskCenterHref,
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
  const rawQuery = await searchParams;
  const query = parseTaskCenterQuery(rawQuery);
  if (hasTaskCenterUnsupportedParams(rawQuery)) redirect(taskCenterHref(query));
  const [formalTasks, reminders] = await Promise.all([
    settleRegionLoad(async () => {
      const page = await getTaskCenterPage(query);
      return { page, hasAnyTasks: page.total > 0 };
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
