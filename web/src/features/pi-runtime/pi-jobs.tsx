'use client';
import {useEffect, useState} from 'react';

type Job = {job_id:string; status:string; command:string; exit_code?:number; output_truncated?:boolean; error?:string};
type JobList = {jobs:Job[]; environment_running?:boolean};
type JobOutput = Job & {output:string; next:number};
const active = (status:string) => ['starting','running','cancelling'].includes(status);
const labels:Record<string,string> = {starting:'启动中',running:'运行中',cancelling:'正在停止',cancelled:'已停止',succeeded:'已完成',failed:'失败',interrupted:'环境中断'};
async function operate<T>(sessionId:string, payload:Record<string,unknown>):Promise<T> {
 const response = await fetch(`/api/platform/pi-runtime/sessions/${encodeURIComponent(sessionId)}/operate`, {
  method:'POST', headers:{'Content-Type':'application/json'}, cache:'no-store',
  body:JSON.stringify({operation:'jobs',payload})
 });
 const body = await response.json();
 if (!response.ok) throw new Error(typeof body.detail==='string'?body.detail:typeof body.message==='string'?body.message:'后台任务读取失败');
 return body;
}
export function PiJobs({sessionId}:{sessionId:string}) {
 const [open,setOpen]=useState(false);
 const [jobs,setJobs]=useState<Job[]>([]);
 const [selected,setSelected]=useState('');
 const [output,setOutput]=useState('');
 const [listError,setListError]=useState('');
 const [logError,setLogError]=useState('');
 const [cancelError,setCancelError]=useState('');
 const [environment,setEnvironment]=useState(true);
 const [cancelling,setCancelling]=useState('');
 const [clipped,setClipped]=useState(false);
 useEffect(()=>{
  if(!open)return;
  let disposed=false;
  let timer:ReturnType<typeof setTimeout>|undefined;
  const refresh=async()=>{
   try {
    const result=await operate<JobList>(sessionId,{operation:'list'});
    if(disposed)return;
    setJobs(result.jobs);setEnvironment(result.environment_running!==false);setListError('');
    if(result.environment_running===false)setSelected('');
   } catch(e){if(!disposed)setListError(e instanceof Error?e.message:'连接中断，正在重新查询');}
   finally{if(!disposed)timer=setTimeout(refresh,2000);}
  };
  void refresh();return()=>{disposed=true;clearTimeout(timer);};
 },[sessionId,open]);
 useEffect(()=>{
  setOutput('');setClipped(false);setLogError('');
  if(!open||!selected)return;
  let disposed=false,offset=0;
  let timer:ReturnType<typeof setTimeout>|undefined;
  const refresh=async()=>{
   try {
    const result=await operate<JobOutput>(sessionId,{operation:'poll',job_id:selected,after:offset});
    if(disposed)return;
    setLogError('');const previous=offset;offset=result.next;
    setJobs(old=>old.map(job=>job.job_id===selected?result:job));
    setOutput(old=>{const text=old+result.output;return text.slice(-200000);});
    if(offset>200000||result.output_truncated)setClipped(true);
    if(active(result.status)||offset>previous)timer=setTimeout(refresh,offset>previous?150:1500);
   } catch(e){if(!disposed){setLogError(e instanceof Error?e.message:'日志读取失败');timer=setTimeout(refresh,2000);}}
  };
  void refresh();return()=>{disposed=true;clearTimeout(timer);};
 },[sessionId,selected,open]);
 async function cancel(jobId:string){
  setCancelling(jobId);setCancelError('');
  try{await operate(sessionId,{operation:'cancel',job_id:jobId});}
  catch(e){setCancelError(e instanceof Error?e.message:'停止请求失败，请检查任务状态');}
  finally{setCancelling('');}
 }
 return <details className='rounded-lg border px-3 py-2 text-xs' onToggle={e=>setOpen(e.currentTarget.open)}>
  <summary className='cursor-pointer'>后台任务{open?` · ${jobs.filter(job=>active(job.status)).length} 个运行中`:''}</summary>
  {open&&<div className='mt-2 max-h-64 space-y-2 overflow-auto'>
   <p className='text-muted-foreground'>中断回复不会停止后台任务。需要停止时，请操作对应任务。</p>
   {[listError,logError,cancelError].filter(Boolean).map((message,index)=><p key={index} role='alert' className='text-destructive'>{message}</p>)}
   {!environment?<p>环境已停止，任务不会自动重跑。历史日志保存在会话文件的 .pi/jobs 中。</p>:!jobs.length?<p>暂无后台任务。</p>:<ul className='space-y-2'>{jobs.map(job=><li key={job.job_id} className='rounded border p-2'>
    <div className='flex items-center justify-between gap-2'><button className='min-w-0 truncate text-left underline' onClick={()=>setSelected(job.job_id)} title={job.command}>{job.command}</button>
     <span className='shrink-0' role='status'>{labels[job.status]??job.status}{job.exit_code!==undefined?` · 退出码 ${job.exit_code}`:''}</span>
     {active(job.status)&&<button className='shrink-0 rounded border px-2 py-1' disabled={!!cancelling||job.status==='cancelling'} onClick={()=>void cancel(job.job_id)} aria-label={`停止任务 ${job.job_id}`}>{cancelling===job.job_id?'提交中…':'停止任务'}</button>}
    </div><p className='text-muted-foreground mt-1'>任务 {job.job_id}</p>{job.error&&<p className='text-destructive'>{job.error}</p>}
   </li>)}</ul>}
   {selected&&<div><p>日志 · {selected}</p>{clipped&&<p className='text-muted-foreground'>日志较长，当前仅显示末段；完整已保留日志可在 .pi/jobs 中下载。</p>}<pre aria-label='后台任务日志' className='mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-2'>{output||'等待输出…'}</pre></div>}
   {jobs.length===200&&<p>当前显示最近 200 个任务。</p>}
  </div>}
 </details>;
}
