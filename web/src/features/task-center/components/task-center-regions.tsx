'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card';
import type { TaskCenterPage, TaskReminderBoard } from '@/features/platform-api/types';
import { TaskReminderBoardView } from '@/features/task-reminders/components/task-reminder-board';
import { loadFormalTaskRegion, loadTaskReminderRegion } from '@/features/task-center/browser-load';
import { TaskCenterList } from '@/features/task-center/components/task-center-list';
import { taskCenterResultAnnouncement } from '@/features/task-center/presentation';
import { taskCenterHref, type TaskCenterQuery } from '@/features/task-center/query';
import {
  initialRegionDisplay,
  markRegionRefreshFailed,
  mergeRegionResult,
  type RegionLoadResult
} from '@/features/task-center/region-load';

type FormalTaskData = { page: TaskCenterPage; hasAnyTasks: boolean };

function RegionError({
  title,
  description,
  retryLabel,
  retrying,
  onRetry
}: {
  title: string;
  description: string;
  retryLabel: string;
  retrying: boolean;
  onRetry: () => void;
}) {
  return (
    <Card role='alert' className='border-destructive/40'>
      <CardHeader>
        <h2 className='text-base leading-snug font-medium'>{title}</h2>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button size='sm' variant='outline' disabled={retrying} onClick={onRetry}>
          {retrying ? '正在重新加载' : retryLabel}
        </Button>
      </CardContent>
    </Card>
  );
}

export function TaskReminderRegion({ initial }: { initial: RegionLoadResult<TaskReminderBoard> }) {
  const router = useRouter();
  const [display, setDisplay] = React.useState(() => initialRegionDisplay(initial));
  const [retrying, setRetrying] = React.useState(false);
  const [announcement, setAnnouncement] = React.useState('');

  React.useEffect(() => {
    setDisplay((current) => mergeRegionResult(current, initial));
  }, [initial]);

  async function retry() {
    setRetrying(true);
    setAnnouncement('');
    try {
      const data = await loadTaskReminderRegion();
      setDisplay(initialRegionDisplay({ state: 'ready', data }));
      setAnnouncement('任务提醒已重新加载。');
    } catch (error) {
      if (error && typeof error === 'object' && 'status' in error) router.refresh();
      else setDisplay(markRegionRefreshFailed);
    } finally {
      setRetrying(false);
    }
  }

  if (display.result.state === 'ready') {
    return (
      <>
        <p role='status' className='sr-only'>
          {announcement}
        </p>
        {display.refreshFailed ? (
          <RegionError
            title='任务提醒刷新失败'
            description='当前仍显示上次成功读取的提醒，可单独重新加载任务提醒。'
            retryLabel='重新加载任务提醒'
            retrying={retrying}
            onRetry={() => void retry()}
          />
        ) : null}
        <TaskReminderBoardView data={display.result.data} />
      </>
    );
  }
  return (
    <RegionError
      title='任务提醒加载失败'
      description='任务提醒暂时无法读取，正式任务列表不受影响。'
      retryLabel='重新加载任务提醒'
      retrying={retrying}
      onRetry={() => void retry()}
    />
  );
}

function FormalTaskRegionContent({
  initial,
  query
}: {
  initial: RegionLoadResult<FormalTaskData>;
  query: TaskCenterQuery;
}) {
  const router = useRouter();
  const [display, setDisplay] = React.useState(() => initialRegionDisplay(initial));
  const [retrying, setRetrying] = React.useState(false);
  const [announcement, setAnnouncement] = React.useState('');

  React.useEffect(() => {
    setDisplay((current) => mergeRegionResult(current, initial));
  }, [initial]);

  async function retry() {
    setRetrying(true);
    setAnnouncement('');
    try {
      const data = await loadFormalTaskRegion(query);
      if (data.canonicalHref) {
        router.replace(data.canonicalHref);
        return;
      }
      setDisplay(
        initialRegionDisplay({
          state: 'ready',
          data: { page: data.page, hasAnyTasks: data.hasAnyTasks }
        })
      );
      setAnnouncement('正式任务已重新加载。');
    } catch (error) {
      if (error && typeof error === 'object' && 'status' in error) router.refresh();
      else setDisplay(markRegionRefreshFailed);
    } finally {
      setRetrying(false);
    }
  }

  if (display.result.state === 'ready') {
    return (
      <>
        <p role='status' className='sr-only'>
          {announcement}
        </p>
        {display.refreshFailed ? (
          <RegionError
            title='正式任务刷新失败'
            description='当前仍显示上次成功读取的正式任务，可单独重新加载正式任务。'
            retryLabel='重新加载正式任务'
            retrying={retrying}
            onRetry={() => void retry()}
          />
        ) : null}
        <TaskCenterList
          data={display.result.data.page}
          query={query}
          hasAnyTasks={display.result.data.hasAnyTasks}
        />
      </>
    );
  }
  return (
    <RegionError
      title='正式任务加载失败'
      description='正式任务列表和计数暂时无法读取，任务提醒不受影响。'
      retryLabel='重新加载正式任务'
      retrying={retrying}
      onRetry={() => void retry()}
    />
  );
}

export function FormalTaskRegion({
  initial,
  query
}: {
  initial: RegionLoadResult<FormalTaskData>;
  query: TaskCenterQuery;
}) {
  const queryKey = taskCenterHref(query);
  const readyPage = initial.state === 'ready' ? initial.data.page : null;
  const itemCount = readyPage?.items?.length ?? 0;
  const [resultAnnouncement, setResultAnnouncement] = React.useState('');

  React.useEffect(() => {
    if (!readyPage) return;
    setResultAnnouncement(taskCenterResultAnnouncement(itemCount, readyPage.total, readyPage.page));
  }, [itemCount, queryKey, readyPage]);

  return (
    <>
      <p role='status' aria-live='polite' className='sr-only'>
        {resultAnnouncement}
      </p>
      <FormalTaskRegionContent key={queryKey} initial={initial} query={query} />
    </>
  );
}
