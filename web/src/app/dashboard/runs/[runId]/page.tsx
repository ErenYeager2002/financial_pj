import { Suspense } from 'react';
import Link from 'next/link';
import { HydrationBoundary, dehydrate } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { buttonVariants } from '@/components/ui/button';
import {
  runApprovalsQueryOptions,
  runQueryOptions,
  runStepsQueryOptions
} from '@/features/runs/api/queries';
import { getRun, getRunApprovals, getRunSteps } from '@/features/runs/api/server';
import { RunDetailView } from '@/features/runs/components/run-detail';
import { RunDetailSkeleton } from '@/features/runs/components/run-detail-skeleton';
import { cn } from '@/lib/utils';
import { getQueryClient } from '@/lib/query-client';

export const metadata = {
  title: '任务详情'
};

interface PageProps {
  params: Promise<{ runId: string }>;
}

export default async function Page({ params }: PageProps): Promise<React.JSX.Element> {
  const { runId } = await params;
  const queryClient = getQueryClient();
  void queryClient.prefetchQuery(runQueryOptions(runId, () => getRun(runId)));
  void queryClient.prefetchQuery(runStepsQueryOptions(runId, () => getRunSteps(runId)));
  void queryClient.prefetchQuery(runApprovalsQueryOptions(runId, () => getRunApprovals(runId)));

  return (
    <PageContainer
      pageTitle='任务详情'
      pageHeaderAction={
        <Link href='/dashboard/runs' className={cn(buttonVariants({ variant: 'outline' }))}>
          返回任务中心
        </Link>
      }
    >
      <HydrationBoundary state={dehydrate(queryClient)}>
        <Suspense fallback={<RunDetailSkeleton />}>
          <RunDetailView runId={runId} />
        </Suspense>
      </HydrationBoundary>
    </PageContainer>
  );
}
