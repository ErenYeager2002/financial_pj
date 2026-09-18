'use client';
import {useState} from 'react';
export type PiDialog = {id:string;method:'confirm'|'select'|'input'|'editor';title?:string;message?:string;options?:string[];placeholder?:string;prefill?:string;expires_at?:number};
export function PiDialogs({requests,reply}:{requests:PiDialog[];reply:(response:Record<string,unknown>)=>Promise<unknown>}) {
 return <>{requests.map(request=><Dialog key={request.id} request={request} reply={reply}/>)}</>;
}
function Dialog({request,reply}:{request:PiDialog;reply:(response:Record<string,unknown>)=>Promise<unknown>}) {
 const [value,setValue]=useState(request.method==='editor'?request.prefill??'':'');
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 async function respond(fields:Record<string,unknown>) {
  if(busy)return;
  setBusy(true);setError('');
  try {await reply({type:'extension_ui_response',id:request.id,...fields});}
  catch(e){setError(e instanceof Error?e.message:'提交失败，请检查请求是否仍有效。');setBusy(false);}
 }
 return <section role='region' aria-label='工具交互请求' className='max-h-72 shrink-0 overflow-auto rounded-xl border border-primary/40 bg-muted/30 p-3 text-sm'>
  <p className='font-medium'>{request.title||'工具需要你的回复'}</p>
  {request.message&&<p className='mt-2 whitespace-pre-wrap break-words'>{request.message}</p>}
  {request.expires_at&&<p className='text-muted-foreground mt-1 text-xs'>有效至 {new Date(request.expires_at).toLocaleTimeString()}，超时后请求自动结束。</p>}
  {request.method==='select'&&<select aria-label='工具请求选项' value={value} disabled={busy} onChange={e=>setValue(e.target.value)} className='bg-background my-2 w-full rounded border p-2'><option value='' disabled>请选择</option>{request.options?.map((option,index)=><option key={index} value={option}>{option}</option>)}</select>}
  {request.method==='input'&&<input aria-label='工具请求输入' value={value} disabled={busy} placeholder={request.placeholder} onChange={e=>setValue(e.target.value)} className='bg-background my-2 w-full rounded border p-2'/>}
  {request.method==='editor'&&<textarea aria-label='工具请求编辑内容' value={value} disabled={busy} onChange={e=>setValue(e.target.value)} rows={4} className='bg-background my-2 w-full rounded border p-2'/>}
  {error&&<p role='alert' className='text-destructive my-2'>{error}</p>}
  <div className='mt-2 flex flex-wrap justify-end gap-2'>
   <button className='rounded border px-3 py-1' disabled={busy} onClick={()=>void respond({cancelled:true})}>取消请求</button>
   {request.method==='confirm'?<><button className='rounded border px-3 py-1' disabled={busy} onClick={()=>void respond({confirmed:false})}>拒绝</button><button className='bg-primary text-primary-foreground rounded px-3 py-1' disabled={busy} onClick={()=>void respond({confirmed:true})}>确认</button></>:<button className='bg-primary text-primary-foreground rounded px-3 py-1' disabled={busy||(request.method==='select'&&!request.options?.includes(value))} onClick={()=>void respond({value})}>提交</button>}
  </div>
 </section>;
}
