'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollableCollection } from '@/components/ui/scrollable-collection';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import type { PlatformFile } from '@/features/platform-api/types';
import { WorkflowMaterialHistory } from '@/features/workflow-agent/components/workflow-material-history';
import { formatDate } from '@/lib/format';
import { cn, formatBytes } from '@/lib/utils';

interface FileListProps {
  files: PlatformFile[];
}

export function FileList({ files }: FileListProps) {
  const router = useRouter();
  const [deletingId, setDeletingId] = useState('');
  const [error, setError] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());
  const groups = Array.from(
    files
      .reduce((map, file) => {
        const key = file.skill_id || 'unassigned';
        const current = map.get(key) ?? {
          label: file.skill_name || file.skill_id || '未归类文件',
          files: [] as typeof files
        };
        current.files.push(file);
        map.set(key, current);
        return map;
      }, new Map<string, { label: string; files: typeof files }>())
      .entries()
  );

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
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <CardTitle>文件记录</CardTitle>
          <div className='flex gap-2'>
            <Button
              type='button'
              size='sm'
              variant='ghost'
              onClick={() => setCollapsedGroups(new Set())}
            >
              全部展开
            </Button>
            <Button
              type='button'
              size='sm'
              variant='ghost'
              onClick={() => setCollapsedGroups(new Set(groups.map(([key]) => key)))}
            >
              全部收起
            </Button>
          </div>
        </div>
        <CardDescription>
          共 {files.length} 个当前文件；同名任务结果只显示最新版本。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className='mb-3 text-sm text-destructive'>{error}</p>}
        <ScrollableCollection ariaLabel='文件分组' contentClassName='space-y-6'>
          {groups.map(([key, group]) => (
            <details
              key={key}
              open={!collapsedGroups.has(key)}
              className='overflow-hidden rounded-lg border'
              onToggle={(event) => {
                const open = event.currentTarget.open;
                setCollapsedGroups((current) => {
                  const next = new Set(current);
                  if (open) next.delete(key);
                  else next.add(key);
                  return next;
                });
              }}
            >
              <summary
                className='cursor-pointer list-none px-4 py-3 hover:bg-muted/40'
                aria-label={`${group.label} 文件列表`}
              >
                <span className='flex flex-wrap items-center gap-2'>
                  <span aria-hidden='true'>{collapsedGroups.has(key) ? '▸' : '▾'}</span>
                  <span className='font-medium'>{group.label}</span>
                  <span className='text-xs text-muted-foreground'>{group.files.length} 个文件</span>
                </span>
              </summary>
              <div
                className='overflow-x-auto border-t px-2 pb-2'
                role='region'
                aria-label={`${group.label}文件列表`}
              >
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
                    {group.files.map((file) => (
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
                {key !== 'unassigned' && (
                  <div className='px-2 pb-2'>
                    <WorkflowMaterialHistory skillId={key} />
                  </div>
                )}
              </div>
            </details>
          ))}
        </ScrollableCollection>
      </CardContent>
    </Card>
  );
}
