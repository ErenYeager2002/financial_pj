'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { Icons } from '@/components/icons';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious
} from '@/components/ui/pagination';
import { ScrollableCollection } from '@/components/ui/scrollable-collection';
import type { PlatformFileOptionPage } from '@/features/platform-api/types';
import { formatBytes } from '@/lib/utils';
import {
  createSelectableInputFilePageLoader,
  isSelectableInputFileDisabled,
  MAX_SELECTED_FILES,
  normalizeSelectedFileLimit,
  selectedFileCountMessage,
  selectedFileLimitMessage,
  toggleSelectedFileIds
} from './selectable-input-file-picker-state';

const EMPTY_PAGE: PlatformFileOptionPage = {
  items: [],
  total: 0,
  page: 1,
  page_size: 25,
  pages: 0
};

export interface SelectableInputFilePickerProps {
  selectedFileIds: string[];
  onSelectedFileIdsChange: (fileIds: string[]) => void;
  onFileNameChange?: (fileId: string, name: string | null) => void;
  disabled?: boolean;
  maxSelectedFiles?: number;
}

export function SelectableInputFilePicker({
  selectedFileIds,
  onSelectedFileIdsChange,
  onFileNameChange,
  disabled = false,
  maxSelectedFiles = MAX_SELECTED_FILES
}: SelectableInputFilePickerProps) {
  const [open, setOpen] = useState(false);
  const [filePage, setFilePage] = useState<PlatformFileOptionPage>(EMPTY_PAGE);
  const [fileSearch, setFileSearch] = useState('');
  const [fileQuery, setFileQuery] = useState('');
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState('');
  const [pageLoader] = useState(() => createSelectableInputFilePageLoader());
  const requestIdRef = useRef(0);
  const files = filePage.items ?? [];
  const selectionLimit = normalizeSelectedFileLimit(maxSelectedFiles);
  const limitMessage = selectedFileLimitMessage(selectedFileIds.length, selectionLimit);

  useEffect(() => {
    return () => {
      requestIdRef.current += 1;
      pageLoader.cancel();
    };
  }, [pageLoader]);

  useEffect(() => {
    if (!open) return;
    setFileSearch('');
    void loadFilePage(1, '');
  }, [open]);

  async function loadFilePage(nextPage: number, nextQuery = fileQuery) {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setFileLoading(true);
    setFileError('');
    const normalizedQuery = nextQuery.trim().slice(0, 100);
    try {
      const nextFilePage = await pageLoader.request(
        nextPage,
        filePage.page_size || 25,
        normalizedQuery
      );
      if (requestId !== requestIdRef.current || !nextFilePage) return;
      setFilePage(nextFilePage);
      setFileQuery(normalizedQuery);
    } catch (loadError) {
      if (requestId !== requestIdRef.current) return;
      setFileError(loadError instanceof Error ? loadError.message : '可选文件加载失败。');
    } finally {
      if (requestId === requestIdRef.current) setFileLoading(false);
    }
  }

  function searchFiles(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadFilePage(1, fileSearch);
  }

  function toggleFile(fileId: string, name: string, checked: boolean) {
    const nextFileIds = toggleSelectedFileIds(
      selectedFileIds,
      fileId,
      checked,
      selectionLimit
    );
    onSelectedFileIdsChange(nextFileIds);
    if (nextFileIds.includes(fileId)) onFileNameChange?.(fileId, name);
    else onFileNameChange?.(fileId, null);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            type='button'
            size='icon'
            variant='outline'
            aria-label='选择任务输入文件'
            title='选择任务输入文件'
            disabled={disabled}
          />
        }
      >
        <Icons.paperclip className='size-4' aria-hidden='true' />
      </DialogTrigger>
      <DialogContent className='flex max-h-[calc(100dvh-2rem)] flex-col overflow-hidden sm:max-w-2xl'>
          <DialogHeader>
            <DialogTitle>选择任务输入文件</DialogTitle>
            <DialogDescription>
              任务输入文件（可选）。普通问答无需选择；助手只读取文件名称等基本信息，任务执行仍受平台权限控制。
            </DialogDescription>
          </DialogHeader>
          <form className='flex gap-2' onSubmit={searchFiles}>
            <Input
              value={fileSearch}
              onChange={(event) => setFileSearch(event.target.value)}
              placeholder='搜索文件名'
              aria-label='搜索可选文件'
              disabled={disabled}
            />
            <Button type='submit' variant='outline' className='shrink-0' disabled={disabled}>
              查询
            </Button>
          </form>
          {fileError && (
            <p role='alert' className='text-sm text-destructive'>
              {fileError}
            </p>
          )}
          {fileLoading && <p className='text-xs text-muted-foreground'>加载文件中…</p>}
          {files.length ? (
            <ScrollableCollection
              ariaLabel='AI 助手可选任务输入文件'
              className='min-h-0 flex-1 rounded-md border p-2'
              contentClassName='grid gap-1'
            >
              {files.map((file) => (
                <label
                  key={file.id}
                  htmlFor={`assistant-file-${file.id}`}
                  className='flex cursor-pointer items-start gap-3 rounded-md p-2 hover:bg-muted/60'
                >
                  <Checkbox
                    id={`assistant-file-${file.id}`}
                    checked={selectedFileIds.includes(file.id)}
                    onCheckedChange={(checked) =>
                      toggleFile(file.id, file.name, checked === true)
                    }
                    disabled={isSelectableInputFileDisabled(
                      selectedFileIds,
                      file.id,
                      disabled,
                      selectionLimit
                    )}
                  />
                  <span className='min-w-0 text-sm' title={file.name}>
                    <span className='block truncate font-medium'>{file.name}</span>
                    <span className='text-xs text-muted-foreground'>
                      {formatBytes(file.size_bytes)} ·{' '}
                      {file.created_at
                        ? new Date(file.created_at).toLocaleString('zh-CN', {
                            hour12: false,
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit'
                          })
                        : '上传时间未记录'}
                    </span>
                    <span className='block truncate text-xs text-muted-foreground'>
                      {file.source_task_type === 'workflow'
                        ? '日清任务'
                        : file.source_task_type === 'run'
                          ? '普通任务'
                          : '直接上传'}{' '}
                      · {file.business_date || '业务日期未记录'}
                      {file.same_content_count > 1
                        ? ` · 相同内容 ${file.same_content_count} 份`
                        : ''}
                    </span>
                  </span>
                </label>
              ))}
            </ScrollableCollection>
          ) : (
            !fileLoading && <p className='text-sm text-muted-foreground'>当前条件下暂无可选文件。</p>
          )}
          {filePage.pages > 1 && (
            <Pagination>
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    href='#'
                    aria-disabled={filePage.page <= 1 || fileLoading || disabled}
                    className={
                      filePage.page <= 1 || fileLoading || disabled
                        ? 'pointer-events-none opacity-50'
                        : undefined
                    }
                    onClick={(event) => {
                      event.preventDefault();
                      if (filePage.page > 1 && !fileLoading && !disabled) {
                        void loadFilePage(filePage.page - 1);
                      }
                    }}
                  />
                </PaginationItem>
                <PaginationItem>
                  <span className='px-2 text-xs text-muted-foreground'>
                    第 {filePage.page} / {filePage.pages} 页 · 共 {filePage.total} 个文件
                  </span>
                </PaginationItem>
                <PaginationItem>
                  <PaginationNext
                    href='#'
                    aria-disabled={filePage.page >= filePage.pages || fileLoading || disabled}
                    className={
                      filePage.page >= filePage.pages || fileLoading || disabled
                        ? 'pointer-events-none opacity-50'
                        : undefined
                    }
                    onClick={(event) => {
                      event.preventDefault();
                      if (filePage.page < filePage.pages && !fileLoading && !disabled) {
                        void loadFilePage(filePage.page + 1);
                      }
                    }}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          )}
          <div className='flex flex-wrap items-center justify-between gap-2 border-t pt-3'>
            <div>
              {limitMessage && (
                <p role='status' className='text-sm text-amber-700 dark:text-amber-400'>
                  {limitMessage}
                </p>
              )}
              <p className='text-xs text-muted-foreground'>
                {selectedFileCountMessage(selectedFileIds.length, selectionLimit)}
              </p>
            </div>
            <div className='flex justify-end'>
              <Button type='button' variant='outline' onClick={() => setOpen(false)}>
                完成
              </Button>
            </div>
          </div>
      </DialogContent>
    </Dialog>
  );
}
