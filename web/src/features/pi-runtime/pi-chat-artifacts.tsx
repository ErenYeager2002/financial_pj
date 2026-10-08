"use client";
import {useState} from 'react';
import type {PiArtifactsView} from './use-pi-artifacts';

export function PiChatArtifacts({view, onRefresh}: {view: PiArtifactsView; onRefresh: () => void}) {
  const [expanded, setExpanded] = useState(false);
  const {files, truncated, error} = view;
  if (!files.length && !error && !truncated) return null;
  return <article aria-label='聊天生成文件' className='my-6 min-w-0 text-sm'>
    <div className='mb-2 flex items-center justify-between gap-4'><span className='text-muted-foreground text-xs'>可下载文件</span><button className='text-muted-foreground text-xs underline' onClick={onRefresh}>刷新</button></div>
    <div className='grid gap-2 sm:grid-cols-2'>{(expanded ? files : files.slice(0, 8)).map(file => <a key={file.path} href={file.href} download className='flex min-w-0 items-center justify-between gap-3 rounded-lg border bg-muted/30 p-3 hover:bg-muted'>
      <span className='min-w-0 break-all'>{file.path}<span className='text-muted-foreground block text-xs'>{Math.ceil(file.size / 1024)} KB</span></span><span className='shrink-0 text-primary'>下载</span>
    </a>)}</div>
    {files.length > 8 && <button className='mt-2 text-xs underline' onClick={() => setExpanded(value => !value)}>{expanded ? '收起文件' : `查看全部 ${files.length} 个文件`}</button>}
    {truncated && <p className='mt-2 text-xs text-muted-foreground'>工作目录文件较多，仅展示部分文件；回复中的文件链接仍可直接下载。</p>}
    {error && <p role='alert' className='mt-2 text-destructive text-xs'>{error}</p>}
  </article>;
}
