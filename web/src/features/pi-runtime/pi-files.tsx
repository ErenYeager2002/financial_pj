'use client';
import { useEffect, useState } from 'react';
import {uploadFile} from './pi-file-transfer';
type Entry={name:string;kind:'file'|'directory';size:number};
type Listing={entries:Entry[];next_offset:number|null};
export function PiFiles({sessionId}:{sessionId:string}) {
 const [source,setSource]=useState('workspace');const [path,setPath]=useState('');
 const [listedAt,setListedAt]=useState('');
 const location=source+'|'+path;
 const [entries,setEntries]=useState<Entry[]>([]);const [next,setNext]=useState<number|null>(null);
 const [refresh,setRefresh]=useState(0);const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [error,setError]=useState('');
 const endpoint=`/api/platform/pi-runtime/sessions/${encodeURIComponent(sessionId)}`;
 async function call(body:unknown) {
  const response=await fetch(endpoint+'/files',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await response.json();if(!response.ok)throw new Error(value.detail??value.message??'文件操作失败');return value;
 }
 useEffect(()=>{let cancelled=false;setError('');setEntries([]);setNext(null);setListedAt('');
  call({action:'list',source,path}).then((value:Listing)=>{if(!cancelled){setEntries(value.entries);setNext(value.next_offset??null);setListedAt(location);}}).catch((e:Error)=>{if(!cancelled)setError(e.message)});
  return ()=>{cancelled=true};
 // The endpoint is derived only from sessionId; the parent remounts on session changes.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[sessionId,source,path,refresh]);
 async function more(){setBusy(true);try{const value:Listing=await call({action:'list',source,path,offset:next});setEntries(old=>[...old,...value.entries]);setNext(value.next_offset)}catch(e){setError(e instanceof Error?e.message:'读取失败')}finally{setBusy(false)}}
 async function upload(files:FileList|null){
  if(!files?.length)return;setBusy(true);setError('');
  try{for(const file of Array.from(files)){
   const done=await uploadFile(sessionId,file,percent=>setMessage(`${file.name} · ${percent}%`));
   setMessage(`已上传：${done.agent_path}`);
  }setSource('inputs');setPath('');setRefresh(v=>v+1)}catch(e){setError(e instanceof Error?e.message:'上传失败')}finally{setBusy(false)}
 }
 const parent=path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
 return <details className='border-input rounded-xl border p-4'>
  <summary className='cursor-pointer text-sm font-medium'>文件 · 上传原件与下载产物</summary>
  <div className='mt-3 flex flex-wrap items-center gap-3'>
   <select aria-label='文件目录' value={source} disabled={busy} onChange={e=>{setSource(e.target.value);setPath('')}} className='bg-background rounded-md border px-2 py-1 text-sm'><option value='workspace'>工作目录</option><option value='inputs'>上传原件（只读）</option></select>
   <label className='text-sm'>上传文件<input aria-label='上传 Pi 文件' type='file' multiple disabled={busy} className='ml-2 max-w-64 text-sm' onChange={e=>{void upload(e.target.files);e.target.value=''}} /></label>
   <button className='rounded border px-2 py-1 text-sm' disabled={busy} onClick={()=>setRefresh(v=>v+1)}>刷新文件</button>
  </div>
  <p className='text-muted-foreground mt-2 break-all text-xs'>{source==='inputs'?'/inputs':'/workspace'}{path?'/'+path:''} · 原件只读；需要修改时先复制到工作目录。</p>
  {message&&<p role='status' className='mt-2 break-all text-xs'>{message}</p>}{error&&<p role='alert' className='text-destructive mt-2 text-sm'>{error}</p>}
  <div className='mt-3 max-h-64 overflow-auto'>
   {path&&<button className='mb-2 text-sm underline' disabled={busy} onClick={()=>setPath(parent)}>上一级</button>}
   {listedAt===location&&entries.map(item=>{const target=path?path+'/'+item.name:item.name;return <div key={item.name} className='flex items-center justify-between gap-4 border-b py-2 text-sm'>
    {item.kind==='directory'?<button disabled={busy} onClick={()=>setPath(target)} className='break-all text-left underline'>{item.name}/</button>:<span className='break-all'>{item.name}</span>}
    {item.kind==='file'&&<a className='shrink-0 underline' href={`${endpoint}/download?${new URLSearchParams({source,path:target})}`} download>{Math.ceil(item.size/1024)} KB · 下载</a>}
   </div>})}
   {listedAt!==location&&!error&&<p role='status' className='text-muted-foreground text-sm'>正在读取目录…</p>}
   {listedAt===location&&!entries.length&&<p className='text-muted-foreground text-sm'>当前目录暂无文件</p>}
   {listedAt===location&&next!==null&&<button className='mt-2 text-sm underline' disabled={busy} onClick={()=>void more()}>加载更多</button>}
  </div>
 </details>;
}
