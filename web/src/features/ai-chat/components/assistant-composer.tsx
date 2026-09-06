'use client';

import { FormEvent, useState } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SelectableInputFilePicker } from '@/features/ai-chat/components/selectable-input-file-picker';
import { MAX_SELECTED_FILES } from '@/features/ai-chat/components/selectable-input-file-picker-state';

interface AssistantComposerProps {
  configured: boolean;
  historyLoading: boolean;
  working: boolean;
  input: string;
  selectedFileIds: string[];
  selectedFileNames: Record<string, string>;
  error: string;
  onInputChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onStop: () => void;
  onSelectedFileIdsChange: (fileIds: string[]) => void;
  onFileNameChange: (fileId: string, name: string | null) => void;
  onRemoveFile: (fileId: string) => void;
}

export function AssistantComposer({
  configured,
  historyLoading,
  working,
  input,
  selectedFileIds,
  selectedFileNames,
  error,
  onInputChange,
  onSubmit,
  onStop,
  onSelectedFileIdsChange,
  onFileNameChange,
  onRemoveFile
}: AssistantComposerProps) {
  const [showAllSelectedFiles, setShowAllSelectedFiles] = useState(false);
  const pickerDisabled = !configured || historyLoading || working;
  const visibleFileIds = showAllSelectedFiles
    ? selectedFileIds
    : selectedFileIds.slice(0, 4);
  const hiddenFileCount = selectedFileIds.length - visibleFileIds.length;

  return (
    <div className='shrink-0 border-t px-4 py-3'>
      <div className='max-h-[min(24dvh,12rem)] overflow-y-auto overscroll-contain' tabIndex={0} role='region' aria-label='输入文件与提示'>
      {selectedFileIds.length > 0 && (
        <div className='mb-2 flex flex-wrap items-center gap-1.5' aria-label='已选择的任务输入文件'>
          {visibleFileIds.map((fileId) => {
            const name = selectedFileNames[fileId] || `文件 ${fileId.slice(0, 8)}`;
            return (
              <span
                key={fileId}
                className='inline-flex max-w-full items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs'
                title={name}
              >
                <span className='min-w-0 max-w-56 break-words'>{name}</span>
                <button
                  type='button'
                  className='platform-action shrink-0 rounded-sm hover:bg-background disabled:pointer-events-none disabled:opacity-50'
                  aria-label={`移除文件 ${name}`}
                  disabled={pickerDisabled}
                  onClick={() => onRemoveFile(fileId)}
                >
                  <Icons.close className='size-3' aria-hidden='true' />
                </button>
              </span>
            );
          })}
          {hiddenFileCount > 0 && (
            <button
              type='button'
              className='platform-action rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground'
              aria-label={`显示另外 ${hiddenFileCount} 个文件`}
              onClick={() => setShowAllSelectedFiles(true)}
            >
              另外 {hiddenFileCount} 个文件
            </button>
          )}
          {showAllSelectedFiles && selectedFileIds.length > 4 && (
            <button
              type='button'
              className='platform-action rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground'
              onClick={() => setShowAllSelectedFiles(false)}
            >
              收起文件
            </button>
          )}
        </div>
      )}
      <p className='mb-2 text-xs text-muted-foreground'>
        任务输入文件（可选）。普通问答无需选择；助手只读取文件名称等基本信息，任务执行仍受平台权限控制。
      </p>
      {error && (
        <p role='alert' className='mb-2 text-sm text-destructive'>
          {error}
        </p>
      )}
      </div>
      <form className='flex items-end gap-2' onSubmit={onSubmit}>
        <SelectableInputFilePicker
          selectedFileIds={selectedFileIds}
          onSelectedFileIdsChange={onSelectedFileIdsChange}
          onFileNameChange={onFileNameChange}
          disabled={pickerDisabled}
          maxSelectedFiles={MAX_SELECTED_FILES}
        />
        <Textarea
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          maxLength={4000}
          rows={3}
          className='max-h-40 min-w-0 flex-1 overflow-y-auto'
          placeholder='输入消息，例如：查看我正在运行的任务，或解释这个 Skill 是做什么的。'
          disabled={pickerDisabled}
          aria-label='发送给 AI 助手的消息'
        />
        {working ? (
          <Button
            type='button'
            size='icon'
            variant='outline'
            className='size-11 shrink-0'
            aria-label='停止生成'
            onClick={onStop}
          >
            <Icons.stop className='size-4' aria-hidden='true' />
          </Button>
        ) : (
          <Button
            type='submit'
            size='icon'
            className='size-11 shrink-0'
            disabled={!configured || historyLoading || !input.trim()}
            aria-label='发送消息'
          >
            <Icons.send className='size-4' aria-hidden='true' />
          </Button>
        )}
      </form>
    </div>
  );
}
