import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious
} from '@/components/ui/pagination';
import { Progress, ProgressLabel } from '@/components/ui/progress';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import type { PlatformRunSummary } from '@/features/runs/api/types';
import { runStateLabel, runStateVariant } from '@/features/runs/run-display';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';

export function RunList({
  runs,
  page,
  pages,
  total,
  state
}: {
  runs: PlatformRunSummary[];
  page: number;
  pages: number;
  total: number;
  state: string;
}) {
  if (!runs.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>暂无任务</CardTitle>
          <CardDescription>从 Skill 目录选择一个已开放的能力并创建任务。</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href='/dashboard/skills' className={cn(buttonVariants())}>
            前往 Skill 目录
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>任务记录</CardTitle>
        <CardDescription>共 {total} 条，失败原因和重试条件由平台统一判断。</CardDescription>
      </CardHeader>
      <CardContent>
        <div
          className='max-h-[36rem] overflow-auto overscroll-contain rounded-lg [scrollbar-gutter:stable]'
          role='region'
          aria-label='任务记录，每页最多 5 项'
        >
          <Table>
          <TableHeader>
            <TableRow>
              <TableHead>任务</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className='min-w-48'>进度</TableHead>
              <TableHead>创建人</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead className='text-right'>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => (
              <TableRow key={run.id}>
                <TableCell>
                  <div className='font-medium'>{run.skill_name}</div>
                  <div className='text-xs text-muted-foreground'>v{run.skill_version}</div>
                  {run.error_message && (
                    <div className='mt-1 max-w-80 truncate text-xs text-destructive'>
                      {run.error_message}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={runStateVariant(run.state)}>{runStateLabel(run.state)}</Badge>
                  {run.can_retry && (
                    <Badge variant='outline' className='ml-1'>
                      可重试
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  <Progress value={run.progress}>
                    <ProgressLabel className='max-w-36 truncate text-xs'>
                      {run.progress_message || '等待更新'}
                    </ProgressLabel>
                    <span className='ml-auto text-xs text-muted-foreground tabular-nums'>
                      {run.progress}%
                    </span>
                  </Progress>
                </TableCell>
                <TableCell>{run.owner_name}</TableCell>
                <TableCell>
                  {formatDate(run.created_at, {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                  })}
                </TableCell>
                <TableCell className='text-right'>
                  <Link
                    href={`/dashboard/runs/${run.id}`}
                    className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                  >
                    查看详情
                  </Link>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
          </Table>
        </div>
        {pages > 1 && (
          <Pagination className='mt-4'>
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious
                  href={`/dashboard/runs?page=${Math.max(page - 1, 1)}${state ? `&state=${encodeURIComponent(state)}` : ''}`}
                  aria-disabled={page <= 1}
                  className={page <= 1 ? 'pointer-events-none opacity-50' : undefined}
                />
              </PaginationItem>
              <PaginationItem className='px-3 text-sm text-muted-foreground'>
                第 {page} / {pages} 页
              </PaginationItem>
              <PaginationItem>
                <PaginationNext
                  href={`/dashboard/runs?page=${Math.min(page + 1, pages)}${state ? `&state=${encodeURIComponent(state)}` : ''}`}
                  aria-disabled={page >= pages}
                  className={page >= pages ? 'pointer-events-none opacity-50' : undefined}
                />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        )}
      </CardContent>
    </Card>
  );
}
