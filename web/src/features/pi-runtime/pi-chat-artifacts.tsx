'use client';
import {useEffect, useState} from 'react';
import {fileDownloadUrl, fileRequest} from './pi-file-transfer';
type Entry = {name: string; kind: 'file'|'directory'; size: number};
type Listing = {entries: Entry[]; next_offset: number|null};
type Artifact = {path: string; size: number};
const excluded = new Set(['node_modules', 'venv', '__pycache__', 'site-packages']);
export function PiChatArtifacts({sessionId, busy, revision}: {sessionId: string; busy: boolean; revision: string}) {
  const [files, setFiles] = useState<Artifact[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [truncated, setTruncated] = useState(false);
  useEffect(() => {
    if (busy) return;
    const controller = new AbortController();
    async function scan() {
      const queue: {path: string; offset: number}[] = [{path: '', offset: 0}];
      const found: Artifact[] = [];
      let requests = 0;
      while (queue.length && requests < 100 && found.length < 1000) {
        const current = queue.shift()!;
        const listing = await fileRequest<Listing>(sessionId, {action: 'list', source: 'workspace', ...current}, controller.signal);
        requests++;
        for (const entry of listing.entries) {
          if (entry.name.startsWith('.') || excluded.has(entry.name)) continue;
          const path = current.path ? `${current.path}/${entry.name}` : entry.name;
          if (entry.kind === 'file') found.push({path, size: entry.size});
          else queue.push({path, offset: 0});
        }
        if (listing.next_offset !== null) queue.push({path: current.path, offset: listing.next_offset});
      }
      if (!controller.signal.aborted) {setFiles(found); setTruncated(queue.length > 0); setError('');}
    }
    void scan().catch(cause => {if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '下载文件读取失败');});
    return () => controller.abort();
  }, [sessionId, busy, revision, refresh]);
  if (!files.length && !error) return null;
  return <article aria-label='聊天生成文件' className='my-6 min-w-0 text-sm'>
    <div className='mb-2 flex items-center justify-between gap-4'><span className='text-muted-foreground text-xs'>可下载文件</span><button className='text-muted-foreground text-xs underline' onClick={() => setRefresh(value => value + 1)}>刷新</button></div>
    <div className='grid gap-2 sm:grid-cols-2'>{(expanded ? files : files.slice(0, 8)).map(file => <a key={file.path} href={fileDownloadUrl(sessionId, 'workspace', file.path)} download className='flex min-w-0 items-center justify-between gap-3 rounded-lg border bg-muted/30 p-3 hover:bg-muted'>
      <span className='min-w-0 break-all'>{file.path}<span className='text-muted-foreground block text-xs'>{Math.ceil(file.size / 1024)} KB</span></span><span className='shrink-0 text-primary'>下载</span>
    </a>)}</div>
    {files.length > 8 && <button className='mt-2 text-xs underline' onClick={() => setExpanded(value => !value)}>{expanded ? '收起文件' : `查看全部 ${files.length} 个文件`}</button>}
    {truncated && <p className='mt-2 text-xs text-muted-foreground'>工作目录文件较多，仅展示部分文件；回复中的文件链接仍可直接下载。</p>}
    {error && <p role='alert' className='mt-2 text-destructive text-xs'>{error}</p>}
  </article>;
}
