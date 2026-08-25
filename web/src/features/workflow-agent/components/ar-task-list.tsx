import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import type { WorkflowBatchRead, WorkflowRead } from '@/features/platform-api/types';
import {
  buildArTaskListRows,
  type ArTaskListRow
} from '@/features/workflow-agent/ar-task-list-presentation';

type ArTaskListProps = {
  batches: WorkflowBatchRead[];
  workflows: WorkflowRead[];
};

function ArTaskListItem({ row }: { row: ArTaskListRow }): React.JSX.Element {
  return (
    <article className='rounded-lg border p-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='min-w-0 space-y-1'>
          <div className='flex flex-wrap items-center gap-2'>
            <h3 className='font-medium'>{row.skillName}</h3>
            <Badge variant='outline'>{row.kindLabel}</Badge>
            <Badge variant={row.status.variant}>{row.status.label}</Badge>
          </div>
          <p className='text-sm font-medium'>{row.dateLabel}</p>
          {row.displayId && (
            <p className='text-xs text-muted-foreground'>任务号：{row.displayId}</p>
          )}
        </div>
        <Link
          href={row.href}
          className='text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring'
          aria-label={`查看${row.dateLabel}的应收核销${row.kindLabel}`}
        >
          查看详情
        </Link>
      </div>

      <div className='mt-3 space-y-2'>
        <div className='flex items-center justify-between gap-3 text-sm'>
          <span className='min-w-0 truncate text-muted-foreground'>{row.progressMessage}</span>
          <span className='shrink-0 tabular-nums'>{row.progress}%</span>
        </div>
        <div
          role='progressbar'
          aria-label={`${row.dateLabel}处理进度`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={row.progress}
          className='h-1.5 overflow-hidden rounded-full bg-muted'
        >
          <div className='h-full bg-primary' style={{ width: `${row.progress}%` }} />
        </div>
        <time dateTime={row.updatedAt} className='block text-xs text-muted-foreground'>
          最近更新：{row.updatedLabel}
        </time>
      </div>

      {row.failureSummary && (
        <p className='mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive'>
          {row.failureSummary}
        </p>
      )}
    </article>
  );
}

export function ArTaskList({ batches, workflows }: ArTaskListProps): React.JSX.Element {
  const rows = buildArTaskListRows(batches, workflows);

  if (!rows.length) {
    return <p className='text-sm text-muted-foreground'>当前没有已提交的应收核销任务。</p>;
  }

  return (
    <div className='space-y-3'>
      {rows.map((row) => (
        <ArTaskListItem key={row.key} row={row} />
      ))}
    </div>
  );
}
