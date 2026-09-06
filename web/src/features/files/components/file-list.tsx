'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem
} from '@/components/ui/pagination';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import type {
  PlatformFile,
  PlatformFileGroupSummary,
  PlatformFilePage
} from '@/features/platform-api/types';
import { WorkflowMaterialHistory } from '@/features/workflow-agent/components/workflow-material-history';
import { formatDate } from '@/lib/format';
import { cn, formatBytes } from '@/lib/utils';
import {
  fileCenterPaginationItems,
  fileCenterUrl,
  fileGroupKey,
  normalizeFileCenterPageSize,
  pageAfterFileDelete
} from '../file-center-pagination';

interface FileListProps {
  groups: PlatformFileGroupSummary[];
  groupTotal: number;
  fileTotal: number;
  page: PlatformFilePage;
  kind: string;
  query: string;
  activeGroup: PlatformFileGroupSummary | null;
  shouldCanonicalizeUrl: boolean;
}

function readableGroupName(group: PlatformFileGroupSummary): string {
  return group.unassigned ? '未归类文件' : group.skill_name || group.skill_id;
}

export function FileList({
  groups,
  groupTotal,
  fileTotal,
  page,
  kind,
  query,
  activeGroup,
  shouldCanonicalizeUrl
}: FileListProps) {
  const router = useRouter();
  const [deletingId, setDeletingId] = useState('');
  const [error, setError] = useState('');
  const [searchValue, setSearchValue] = useState(query);
  const files = page.items ?? [];
  const activeKey = activeGroup ? fileGroupKey(activeGroup) : '';
  const pageSize = normalizeFileCenterPageSize(page.page_size);

  useEffect(() => {
    setSearchValue(query);
  }, [query]);

  useEffect(() => {
    if (!shouldCanonicalizeUrl || !activeGroup) return;
    router.replace(
      fileCenterUrl({
        kind,
        query,
        group: activeGroup,
        page: page.page,
        pageSize
      })
    );
  }, [activeGroup, kind, page.page, pageSize, query, router, shouldCanonicalizeUrl]);

  function navigate(next: {
    kind?: string;
    query?: string;
    group?: PlatformFileGroupSummary | null;
    page?: number;
    pageSize?: number;
  }) {
    router.push(
      fileCenterUrl({
        kind: next.kind ?? kind,
        query: next.query ?? query,
        group: next.group === undefined ? activeGroup : next.group,
        page: next.page ?? 1,
        pageSize: next.pageSize ?? pageSize
      })
    );
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    navigate({ query: searchValue.trim().slice(0, 100), page: 1 });
  }

  async function deleteFile(fileId: string) {
    const file = files.find((item) => item.id === fileId);
    if (!file || !window.confirm(`确认删除文件“${file.name}”吗？删除后不能恢复。`)) return;
    setDeletingId(fileId);
    setError('');
    const response = await fetch(`/api/platform/files/${encodeURIComponent(fileId)}`, {
      method: 'DELETE'
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;
      setError(body?.detail ?? '文件删除失败。');
      setDeletingId('');
      return;
    }
    const nextPage = pageAfterFileDelete(page.page, files.length);
    if (nextPage !== page.page) {
      navigate({ page: nextPage });
    } else {
      router.refresh();
    }
    setDeletingId('');
  }

  return (
    <div className='simple-file-center space-y-5'>
      <form className='simple-file-filters' onSubmit={submitSearch}>
        <label className='simple-search' htmlFor='file-query'>
          <span className='sr-only'>文件名</span>
          <Input id='file-query' value={searchValue} onChange={(event) => setSearchValue(event.target.value)} placeholder='搜索文件名' />
        </label>
        <label>
          <span className='sr-only'>业务分组</span>
          <select value={activeKey} aria-label='业务分组'
            onChange={(event) => navigate({ group: groups.find((group) => fileGroupKey(group) === event.target.value) ?? null, page: 1 })}>
            {!activeGroup ? <option value=''>暂无分组</option> : null}
            {groups.map((group) => <option key={fileGroupKey(group)} value={fileGroupKey(group)}>{readableGroupName(group)} · {group.file_count}</option>)}
          </select>
        </label>
        <label>
          <span className='sr-only'>文件类型</span>
          <select value={kind} aria-label='文件类型筛选' onChange={(event) => navigate({ kind: event.target.value, page: 1 })}>
            <option value=''>全部类型</option><option value='input'>上传文件</option><option value='output'>结果文件</option>
          </select>
        </label>
        <Button type='submit' variant='outline'>查询</Button>
        {query || kind ? <Link href={fileCenterUrl({ group: activeGroup, page: 1, pageSize })} className='simple-text-action'>清除筛选</Link> : null}
      </form>
      {error ? <p role='alert' className='text-sm text-destructive'>{error}</p> : null}
      <section aria-label='文件列表' className='min-w-0'>
        <div className='mb-3 flex flex-wrap items-center justify-between gap-2'>
          <h2 className='text-sm font-medium'>{activeGroup ? readableGroupName(activeGroup) : '文件'}
            <span className='ml-2 font-normal text-muted-foreground'>{page.total} 个</span>
          </h2>
          <span className='text-xs text-muted-foreground'>全部 {fileTotal} 个文件 · {groupTotal} 个分组</span>
        </div>
        {files.length && activeGroup ? (
          <>
            <Table className='simple-file-table' role='table'>
              <TableHeader><TableRow>
                <TableHead>文件名称</TableHead><TableHead>业务来源</TableHead>
                <TableHead>创建时间</TableHead><TableHead className='text-right'>操作</TableHead>
              </TableRow></TableHeader>
              <TableBody>{files.map((file) => <FileRow key={file.id} file={file} deleting={deletingId === file.id} onDelete={deleteFile} />)}</TableBody>
            </Table>
            <GroupPagination page={page.page} pages={page.pages} total={page.total} pageSize={pageSize}
              kind={kind} query={query} group={activeGroup}
              onPageSizeChange={(nextPageSize) => navigate({ page: 1, pageSize: nextPageSize })} />
          </>
        ) : (
          <div className='py-12 text-center text-sm text-muted-foreground'>
            <p>当前条件下没有文件。</p>
            {page.total > 0 && activeGroup ? <Link className='simple-text-action' href={fileCenterUrl({ kind, query, group: activeGroup, page: 1, pageSize })}>返回第一页</Link> : null}
          </div>
        )}
      </section>
      {activeGroup && !activeGroup.unassigned ? <WorkflowMaterialHistory skillId={activeGroup.skill_id} /> : null}
    </div>
  );
}

function FileRow({
  file,
  deleting,
  onDelete
}: {
  file: PlatformFile;
  deleting: boolean;
  onDelete: (fileId: string) => void;
}) {
  return (
    <TableRow className='simple-file-row' role='row'>
      <TableCell role='cell'>
        <Link href={`/dashboard/files/${encodeURIComponent(file.id)}`} className='simple-title-link font-medium leading-6' title={file.name}>{file.name}</Link>
        <p className='mt-1 text-xs text-muted-foreground'>
          {file.kind === 'output' ? '结果文件' : '上传文件'} · {formatBytes(file.size_bytes)}
          {file.same_content_count > 1 ? ` · 同内容 ${file.same_content_count} 份` : ''}
        </p>
      </TableCell>
      <TableCell role='cell'>
        <span className='simple-mobile-label'>业务来源</span>
        <p className='tabular-nums'>{file.business_date || '—'}</p>
        <p className='mt-1 text-xs text-muted-foreground'>
          {file.source_task_type === 'workflow' ? '日清任务' : file.source_task_type === 'run' ? '普通任务' : '直接上传'}
        </p>
      </TableCell>
      <TableCell role='cell'>
        <span className='simple-mobile-label'>创建时间</span>
        <p className='tabular-nums'>{formatDate(file.created_at ?? undefined)}</p>
        {file.material_version != null || file.skill_version ? <p className='mt-1 text-xs text-muted-foreground'>
          {file.material_version != null ? `材料版本 ${file.material_version}` : `Skill ${file.skill_version}`}
        </p> : null}
      </TableCell>
      <TableCell role='cell'>
        <div className='simple-file-actions'>
          <a href={`/api/platform/files/${encodeURIComponent(file.id)}/download`} download className='simple-text-action'>下载</a>
          <details className='simple-file-more'>
            <summary aria-label={`${file.name} 更多信息与操作`}>更多</summary>
            <div className='simple-file-options'>
              <Link href={`/dashboard/files/${encodeURIComponent(file.id)}`} className='simple-text-action'>查看详情</Link>
              <p className='text-xs text-muted-foreground'>保留至 {formatDate(file.expires_at ?? undefined)}</p>
              <Button type='button' size='sm' variant='ghost' className='text-destructive'
                disabled={!file.can_delete || deleting}
                title={file.delete_block_reason || '删除未被任务引用的上传文件'} aria-label={`删除文件 ${file.name}`}
                onClick={() => onDelete(file.id)}>{deleting ? '删除中…' : '删除文件'}</Button>
              {!file.can_delete && file.delete_block_reason ? <p className='text-xs text-muted-foreground'>{file.delete_block_reason}</p> : null}
            </div>
          </details>
        </div>
      </TableCell>
    </TableRow>
  );
}

function GroupPagination({
  page,
  pages,
  total,
  pageSize,
  kind,
  query,
  group,
  onPageSizeChange
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  kind: string;
  query: string;
  group: PlatformFileGroupSummary;
  onPageSizeChange: (pageSize: number) => void;
}) {
  if (!pages) return null;
  const href = (targetPage: number) =>
    fileCenterUrl({ kind, query, group, page: targetPage, pageSize });
  const disabledPrevious = page <= 1;
  const disabledNext = page >= pages;
  const items = fileCenterPaginationItems(page, pages);

  return (
    <div className='flex flex-wrap items-center justify-between gap-3 border-t pt-3'>
      <p className='text-sm text-muted-foreground'>
        第 {page} / {pages} 页，共 {total} 个文件
      </p>
      <div className='flex flex-wrap items-center gap-3'>
        <label className='flex items-center gap-2 text-sm text-muted-foreground'>
          每页
          <select
            value={pageSize}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            className='min-h-11 rounded-lg border bg-background px-2 text-foreground md:min-h-9'
            aria-label='每页文件数量'
          >
            <option value='25'>25 条</option>
            <option value='50'>50 条</option>
          </select>
        </label>
        <Pagination className='mx-0 w-auto'>
          <PaginationContent>
            <PaginationItem>
              <PaginationNavigationLink
                href={href(Math.max(page - 1, 1))}
                disabled={disabledPrevious}
                ariaLabel='上一页'
              >
                上一页
              </PaginationNavigationLink>
            </PaginationItem>
            {items.map((item, index) => (
              <PaginationItem key={`${item}-${index}`}>
                {item === 'ellipsis' ? (
                  <PaginationEllipsis />
                ) : (
                  <PaginationNavigationLink
                    href={href(item)}
                    active={item === page}
                    ariaLabel={`第 ${item} 页`}
                  >
                    {item}
                  </PaginationNavigationLink>
                )}
              </PaginationItem>
            ))}
            <PaginationItem>
              <PaginationNavigationLink
                href={href(Math.min(page + 1, pages))}
                disabled={disabledNext}
                ariaLabel='下一页'
              >
                下一页
              </PaginationNavigationLink>
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </div>
    </div>
  );
}

function PaginationNavigationLink({
  href,
  children,
  disabled = false,
  active = false,
  ariaLabel
}: {
  href: string;
  children: React.ReactNode;
  disabled?: boolean;
  active?: boolean;
  ariaLabel: string;
}) {
  return (
    <Link
      href={href}
      prefetch={false}
      aria-label={ariaLabel}
      aria-current={active ? 'page' : undefined}
      aria-disabled={disabled || undefined}
      tabIndex={disabled ? -1 : undefined}
      className={cn(
        buttonVariants({ variant: active ? 'default' : 'outline', size: 'sm' }),
        'platform-action',
        disabled && 'pointer-events-none opacity-50'
      )}
    >
      {children}
    </Link>
  );
}
