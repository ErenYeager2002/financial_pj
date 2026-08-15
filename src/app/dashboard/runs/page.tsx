import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { listRuns } from '@/features/runs/api/server';
import { RunList } from '@/features/runs/components/run-list';

export const metadata = {
  title: '任务中心'
};

type PageProps = {
  searchParams: Promise<{ page?: string; state?: string }>;
};

export default async function Page({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(Number.parseInt(params.page ?? '1', 10) || 1, 1);
  const state = params.state ?? '';
  const result = await listRuns(page, 20, state);
  return (
    <PageContainer pageTitle='任务中心' pageDescription='查看任务状态、处理进度和结果文件'>
      <form className='mb-4 flex flex-wrap items-end gap-2' method='get'>
        <label className='grid gap-1 text-sm'>
          <span className='text-muted-foreground'>任务状态</span>
          <select
            name='state'
            defaultValue={state}
            className='h-9 rounded-md border bg-background px-3'
          >
            <option value=''>全部状态</option>
            <option value='waiting_confirmation'>待确认</option>
            <option value='queued'>排队中</option>
            <option value='running'>执行中</option>
            <option value='succeeded'>已完成</option>
            <option value='failed'>失败</option>
            <option value='timed_out'>已超时</option>
          </select>
        </label>
        <Button type='submit' variant='outline'>
          筛选
        </Button>
      </form>
      <RunList
        runs={result.items ?? []}
        page={result.page}
        pages={result.pages}
        total={result.total}
        state={state}
      />
    </PageContainer>
  );
}
