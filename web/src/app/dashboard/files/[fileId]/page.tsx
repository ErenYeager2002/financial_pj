import Link from 'next/link';
import { notFound } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getFile } from '@/features/files/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { formatDate } from '@/lib/format';
import { cn, formatBytes } from '@/lib/utils';

export const metadata = {
  title: '文件详情'
};

type PageProps = {
  params: Promise<{ fileId: string }>;
};

export default async function Page({ params }: PageProps) {
  const { fileId } = await params;
  let file;
  try {
    file = await getFile(fileId);
  } catch (error) {
    if (error instanceof PlatformApiError && error.status === 404) notFound();
    throw error;
  }
  const sourceLabel =
    file.source_task_type === 'workflow'
      ? '日清任务'
      : file.source_task_type === 'run'
        ? '普通任务'
        : '直接上传';

  return (
    <PageContainer
      pageTitle='文件详情'
      pageHeaderAction={
        <Link href='/dashboard/files' className={cn(buttonVariants({ variant: 'outline' }))}>
          返回文件中心
        </Link>
      }
    >
      <div className='grid gap-4 lg:grid-cols-2'>
        <Card>
          <CardHeader>
            <div className='flex flex-wrap items-center gap-2'>
              <CardTitle className='break-all'>{file.name}</CardTitle>
              <Badge variant='outline'>{file.kind === 'output' ? '结果文件' : '上传文件'}</Badge>
            </div>
            <CardDescription>{formatBytes(file.size_bytes)}</CardDescription>
          </CardHeader>
          <CardContent className='space-y-3'>
            <dl className='grid gap-3 sm:grid-cols-2'>
              <div>
                <dt className='text-sm text-muted-foreground'>来源</dt>
                <dd>{sourceLabel}</dd>
              </div>
              <div>
                <dt className='text-sm text-muted-foreground'>业务日期</dt>
                <dd>{file.business_date || '未记录'}</dd>
              </div>
              <div>
                <dt className='text-sm text-muted-foreground'>Skill 版本</dt>
                <dd>{file.skill_version || '未记录'}</dd>
              </div>
              <div>
                <dt className='text-sm text-muted-foreground'>材料版本</dt>
                <dd>{file.material_version == null ? '不适用或未记录' : file.material_version}</dd>
              </div>
              <div>
                <dt className='text-sm text-muted-foreground'>上传时间</dt>
                <dd>{formatDate(file.created_at ?? undefined)}</dd>
              </div>
              <div>
                <dt className='text-sm text-muted-foreground'>相同内容记录</dt>
                <dd>{file.same_content_count} 份</dd>
              </div>
            </dl>
            <div className='rounded-lg bg-muted/50 p-3 text-sm'>
              <p className='text-muted-foreground'>SHA-256 校验值</p>
              <p className='mt-1 break-all font-mono text-xs'>{file.sha256}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>关联记录</CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            {file.source_task_id ? (
              <p className='text-sm'>来源任务：{file.source_task_id}</p>
            ) : (
              <p className='text-sm text-muted-foreground'>没有登记来源任务。</p>
            )}
            {file.referenced_workflow_ids?.length ? (
              <div className='space-y-1 text-sm'>
                <p className='text-muted-foreground'>日清任务记录</p>
                {file.referenced_workflow_ids.map((workflowId) => (
                  <Link
                    key={workflowId}
                    href={`/dashboard/workflows/${encodeURIComponent(workflowId)}`}
                    className='block text-primary underline-offset-4 hover:underline'
                  >
                    {workflowId}
                  </Link>
                ))}
              </div>
            ) : null}
            {file.referenced_run_ids?.length ? (
              <div className='space-y-1 text-sm'>
                <p className='text-muted-foreground'>普通任务记录</p>
                {file.referenced_run_ids.map((runId) => (
                  <Link
                    key={runId}
                    href={`/dashboard/runs/${encodeURIComponent(runId)}`}
                    className='block text-primary underline-offset-4 hover:underline'
                  >
                    {runId}
                  </Link>
                ))}
              </div>
            ) : null}
            {file.audit_href ? (
              <Link href={file.audit_href} className={cn(buttonVariants({ variant: 'outline' }))}>
                查看关联审计
              </Link>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
