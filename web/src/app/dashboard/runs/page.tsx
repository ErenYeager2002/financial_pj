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
      const hasFilters = Boolean(
        query.query ||
          query.skillId ||
          query.viewState ||
          query.businessDateFrom ||
          query.businessDateTo
      );
      const basePage = hasFilters
        ? await getTaskCenterPage({
            ...query,
            page: 1,
            query: '',
            skillId: '',
            viewState: '',
            businessDateFrom: '',
            businessDateTo: ''
          })
        : page;
      return { page, hasAnyTasks: basePage.total > 0 };
    }),
    settleRegionLoad(getTaskReminderBoard)
  ]);
  if (formalTasks.state === 'ready') {
    const canonicalHref = taskCenterPageRedirect(query, formalTasks.data.page.pages);
    if (canonicalHref) redirect(canonicalHref);
  }

  return (
    <PageContainer pageTitle='我的任务' headingLevel={1} compact>
      <div className='space-y-5'>
        <details className='simple-reminders' open={reminders.state !== 'ready'}>
          <summary>
            任务提醒与补查
            {reminders.state === 'ready'
              ? ` · ${reminders.data.reminders?.length ?? 0} 条提醒 · ${reminders.data.check_failures?.length ?? 0} 项检查失败`
              : ' · 加载失败'}
          </summary>
          <aside className='min-w-0 space-y-4 pt-3' aria-label='任务提醒区域'>
            <TaskReminderRegion initial={reminders} />
          </aside>
        </details>
        <section className='platform-task-main' aria-label='正式任务区域'>
          <FormalTaskRegion initial={formalTasks} query={query} />
        </section>
      </div>
    </PageContainer>
  );
}
