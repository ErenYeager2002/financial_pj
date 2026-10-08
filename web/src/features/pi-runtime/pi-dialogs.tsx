'use client';
import {useEffect,useState} from 'react';
import type {PiDialog} from './pi-dialog-gate';
export type {PiDialog} from './pi-dialog-gate';
export function PiDialogs({requests,available,allowApproval=true,reply}:{requests:PiDialog[];available:boolean;allowApproval?:boolean;reply:(response:Record<string,unknown>)=>Promise<unknown>}) {
 return <>{requests.map(request=><Dialog key={request.id} request={request} available={available} allowApproval={allowApproval} reply={reply}/>)}</>;
}
function Dialog({request,available,allowApproval,reply}:{request:PiDialog;available:boolean;allowApproval:boolean;reply:(response:Record<string,unknown>)=>Promise<unknown>}) {
 const [value,setValue]=useState(request.method==='editor'?request.prefill??'':'');
 const [now,setNow]=useState(Date.now);
 useEffect(()=>{if(request.expires_at===undefined)return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer)},[request.expires_at]);
 const expired=request.expires_at!==undefined&&(!Number.isFinite(request.expires_at)||request.expires_at<=now);
 const blocked=!available||expired;
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 async function respond(fields:Record<string,unknown>) {
  if(busy||blocked||(!allowApproval&&fields.cancelled!==true&&fields.confirmed!==false))return;
  setBusy(true);setError('');
  try {await reply({type:'extension_ui_response',id:request.id,...fields});}
  catch(e){setError(e instanceof Error?e.message:'提交失败，请检查请求是否仍有效。');setBusy(false);}
 }
 return <section role='region' aria-label='工具交互请求' className='max-h-72 shrink-0 overflow-auto rounded-xl border border-primary/40 bg-muted/30 p-3 text-sm'>
  <p className='font-medium'>{request.title||'工具需要你的回复'}</p>
  {request.message&&<p className='mt-2 whitespace-pre-wrap break-words'>{request.message}</p>}
  {request.expires_at&&<p className='text-muted-foreground mt-1 text-xs'>有效至 {new Date(request.expires_at).toLocaleTimeString()}，超时后请求自动结束。</p>}
  {request.method==='select'&&<select aria-label='工具请求选项' value={value} disabled={busy||blocked||!allowApproval} onChange={e=>setValue(e.target.value)} className='bg-background my-2 w-full rounded border p-2'><option value='' disabled>请选择</option>{request.options?.map((option,index)=><option key={index} value={option}>{option}</option>)}</select>}
  {request.method==='input'&&<input aria-label='工具请求输入' value={value} disabled={busy||blocked||!allowApproval} placeholder={request.placeholder} onChange={e=>setValue(e.target.value)} className='bg-background my-2 w-full rounded border p-2'/>}
  {request.method==='editor'&&<textarea aria-label='工具请求编辑内容' value={value} disabled={busy||blocked||!allowApproval} onChange={e=>setValue(e.target.value)} rows={4} className='bg-background my-2 w-full rounded border p-2'/>}
  {blocked&&<p role='status' className='text-muted-foreground my-2'>{expired?'此请求已过期，等待工具后续结果。':'正在同步会话，请等待连接恢复后再回复。'}</p>}
  {!allowApproval&&<p role='status' className='text-muted-foreground my-2'>Skill 权限已变化，目前只能拒绝或取消此请求。</p>}
  {error&&<p role='alert' className='text-destructive my-2'>{error}</p>}
  <div className='mt-2 flex flex-wrap justify-end gap-2'>
   <button className='rounded border px-3 py-1' disabled={busy||blocked} onClick={()=>void respond({cancelled:true})}>取消请求</button>
   {request.method==='confirm'?<><button className='rounded border px-3 py-1' disabled={busy||blocked} onClick={()=>void respond({confirmed:false})}>拒绝</button><button className='bg-primary text-primary-foreground rounded px-3 py-1' disabled={busy||blocked||!allowApproval} onClick={()=>void respond({confirmed:true})}>确认</button></>:<button className='bg-primary text-primary-foreground rounded px-3 py-1' disabled={busy||blocked||!allowApproval||(request.method==='select'&&!request.options?.includes(value))} onClick={()=>void respond({value})}>提交</button>}
  </div>
 </section>;
}
