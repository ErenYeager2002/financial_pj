'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious
} from '@/components/ui/pagination';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import type { PlatformFilePage } from '@/features/platform-api/types';
import { formatDate } from '@/lib/format';
import { cn, formatBytes } from '@/lib/utils';

interface FileListProps {
  result: PlatformFilePage;
  kind: string;
  query: string;
}

function pageUrl(page: number, kind: string, query: string): string {
  const params = new URLSearchParams({ page: String(page) });
  if (kind) params.set('kind', kind);
  if (query) params.set('query', query);
  return `/dashboard/files?${params}`;
}

export function FileList({ result, kind, query }: FileListProps) {
  const router = useRouter();
  const [deletingId, setDeletingId] = useState('');
  const [error, setError] = useState('');
  const files = result.items ?? [];

  async function deleteFile(fileId: string) {
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
    router.refresh();
    setDeletingId('');
  }

  if (!files.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>暂无文件</CardTitle>
          <CardDescription>上传文件或运行 Skill 后，文件会显示在这里。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>文件记录</CardTitle>
        <CardDescription>
          共 {result.total} 个文件；保留日期用于后续清理策略，当前不会自动删除文件。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className='mb-3 text-sm text-destructive'>{error}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>文件</TableHead>
              <TableHead>类型</TableHead>
              <TableHead>大小</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>保留至</TableHead>
              <TableHead className='text-right'>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.map((file) => (
              <TableRow key={file.id}>
                <TableCell>
                  <p className='max-w-72 truncate font-medium'>{file.name}</p>
                  <p className='text-xs text-muted-foreground'>
                    SHA-256 {file.sha256.slice(0, 12)}…
                  </p>
                </TableCell>
                <TableCell>{file.kind === 'output' ? '结果文件' : '上传文件'}</TableCell>
                <TableCell>{formatBytes(file.size_bytes)}</TableCell>
                <TableCell>{formatDate(file.created_at ?? undefined)}</TableCell>
                <TableCell>{formatDate(file.expires_at ?? undefined)}</TableCell>
                <TableCell className='space-x-2 text-right'>
                  <a
                    href={`/api/platform/files/${encodeURIComponent(file.id)}/download`}
                    className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                  >
                    下载
                  </a>
                  <Button
                    type='button'
                    size='sm'
                    variant='destructive'
                    disabled={!file.can_delete || deletingId === file.id}
                    title={file.delete_block_reason || '删除未被任务引用的上传文件'}
                    onClick={() => void deleteFile(file.id)}
                  >
                    {deletingId === file.id ? '删除中…' : '删除'}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {result.pages > 1 && (
          <Pagination className='mt-4'>
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious
                  href={pageUrl(Math.max(result.page - 1, 1), kind, query)}
                  aria-disabled={result.page <= 1}
                  className={result.page <= 1 ? 'pointer-events-none opacity-50' : undefined}
                />
              </PaginationItem>
              <PaginationItem className='px-3 text-sm text-muted-foreground'>
                第 {result.page} / {result.pages} 页
              </PaginationItem>
              <PaginationItem>
                <PaginationNext
                  href={pageUrl(Math.min(result.page + 1, result.pages), kind, query)}
                  aria-disabled={result.page >= result.pages}
                  className={
                    result.page >= result.pages ? 'pointer-events-none opacity-50' : undefined
                  }
                />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        )}
      </CardContent>
    </Card>
  );
}
