'use client';
import {createClientId} from '@/lib/client-id';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {IconArrowUp,IconSquare,IconPlus,IconAdjustmentsHorizontal,IconLayoutSidebar,IconEdit,IconX} from '@tabler/icons-react';
import {PiChatMessages,messageKey as key,type ChatMessage as Message} from './pi-chat-messages';
import styles from './pi-chat-design.module.css';
import {PiCommands,type PiCommand} from './pi-commands';
import {uploadFile,type UploadedFile} from './pi-file-transfer';
import {PiChatArtifacts} from './pi-chat-artifacts';
import {PiDialogs,type PiDialog} from './pi-dialogs';
import type {PiSession} from './pi-workspace';

type Model={id:string;provider:string;name?:string};
type Event={sequence:number;generation?:number;kind:string;event?:Record<string,unknown>};
type Poll={running:boolean;generation?:number;activity?:{busy:boolean;phase:string}|null;mode?:string;instance_id?:string;events:Event[];next:number;gap?:boolean;pending_dialogs?:PiDialog[]};
async function api<T>(path:string,body?:unknown):Promise<T>{
 const response=await fetch('/api/platform/pi-runtime'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
 const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:typeof value.message==='string'?value.message:'Agent 请求失败');return value;
}
function ChatSession({sessionId,controls}:{sessionId:string;controls:ReactNode}){
 const composer=useRef<HTMLTextAreaElement>(null);
 const [commands,setCommands]=useState<PiCommand[]>([]);const [commandsOpen,setCommandsOpen]=useState(false);
 const [messages,setMessages]=useState<Message[]>([]);const [input,setInput]=useState('');const [error,setError]=useState('');
 const [running,setRunning]=useState(false);const [mode,setMode]=useState('');const [working,setWorking]=useState(false);const [sending,setSending]=useState(false);const [queueMode,setQueueMode]=useState('follow_up');
 const [models,setModels]=useState<Model[]>([]);const [model,setModel]=useState('');const [thinking,setThinking]=useState('high');const [pending,setPending]=useState(0);
 const [dialogs,setDialogs]=useState<PiDialog[]>([]);
 useEffect(()=>{const el=composer.current;if(el){el.style.height='auto';el.style.height=Math.min(192,Math.max(96,el.scrollHeight))+'px'}},[input]);
 const picker=useRef<HTMLInputElement>(null);const uploadController=useRef<AbortController|null>(null);
 const [draftsLoaded,setDraftsLoaded]=useState(false);
 useEffect(()=>{try{const saved=JSON.parse(sessionStorage.getItem('pi-attachments:'+sessionId)??'[]');const pendingFiles=JSON.parse(sessionStorage.getItem('pi-attachment-send:'+sessionId)??'[]');const uncertain=Array.isArray(pendingFiles)?pendingFiles:[];if(uncertain.length)setError('上一条附件消息的接收状态待核实，请先查看聊天记录，避免重复发送。');if(Array.isArray(saved))setAttachments(saved.filter((file:UploadedFile)=>file&&typeof file.name==='string'&&typeof file.agent_path==='string'&&file.agent_path.startsWith('/inputs/')&&!uncertain.includes(file.agent_path)))}catch{}setDraftsLoaded(true);return()=>{uploadController.current?.abort()}},[sessionId]);const uploadLock=useRef(false);const dragDepth=useRef(0);
 const [dragging,setDragging]=useState(false);const [uploading,setUploading]=useState(false);const [uploadProgress,setUploadProgress]=useState('');
 const [attachments,setAttachments]=useState<UploadedFile[]>([]);
 useEffect(()=>{if(draftsLoaded){try{sessionStorage.setItem('pi-attachments:'+sessionId,JSON.stringify(attachments))}catch{}}},[attachments,sessionId,draftsLoaded]);
 const submittedAttachments=useRef(new Map<string,string[]>());const attachmentSnapshot=useRef<string[]>([]);
 const activity=useRef<{busy:boolean;phase:string}|null>(null);
 const submitted=useRef(new Map<string,string>());const starting=useRef(false);
 const prefix=useRef(createClientId());const viewport=useRef<HTMLDivElement>(null);const follow=useRef(true);
 const op=<T,>(operation:string,payload:unknown={})=>api<T>(`/sessions/${encodeURIComponent(sessionId)}/operate`,{operation,payload});
 const rpc=(type:string,params:Record<string,unknown>={},originalDraft?:string)=>{const id=prefix.current+':'+type+':'+createClientId();if(['prompt','steer','follow_up'].includes(type)&&typeof params.message==='string'){submitted.current.set(id,originalDraft??params.message);submittedAttachments.current.set(id,attachmentSnapshot.current)}return op('send',{command:{...params,type,id}}).catch(cause=>{submitted.current.delete(id);submittedAttachments.current.delete(id);throw cause})};
 useEffect(()=>{if(follow.current&&viewport.current)viewport.current.scrollTop=viewport.current.scrollHeight},[messages]);
 useEffect(()=>{const el=viewport.current;if(!el)return;const observer=new ResizeObserver(()=>{if(follow.current)el.scrollTop=el.scrollHeight});for(const child of Array.from(el.children))observer.observe(child);const mutation=new MutationObserver(()=>{for(const child of Array.from(el.children))observer.observe(child);if(follow.current)el.scrollTop=el.scrollHeight});mutation.observe(el,{childList:true});return()=>{observer.disconnect();mutation.disconnect()}},[]);
 useEffect(()=>{
  let disposed=false,cursor=0,instance='',generation:number|undefined,hydrated=false,live=false;let timer:ReturnType<typeof setTimeout>|undefined;
  const hydrate=async()=>{await rpc('get_messages');await rpc('get_state');await rpc('get_available_models');await rpc('get_commands')};
  const upsert=(message:Message)=>setMessages(old=>{const index=old.findIndex(item=>key(item)===key(message));return index<0?[...old,message]:old.map((item,i)=>i===index?message:item)});
  const poll=async()=>{try{
   const value=await op<Poll>('poll',{after:cursor});if(disposed)return;
   live=value.running;setRunning(live);setMode(value.mode??'');setDialogs(value.pending_dialogs??[]);
   if((instance&&value.instance_id&&instance!==value.instance_id)||(generation!==undefined&&value.generation!==undefined&&generation!==value.generation)){cursor=0;hydrated=false;instance=value.instance_id??instance;generation=value.generation;activity.current=null;setSending(false);if(submitted.current.size){submitted.current.clear();submittedAttachments.current.clear();setError('运行环境已变化，上一条消息的接收状态未知，请检查历史后再决定是否发送。')}return}
   instance=value.instance_id??instance;generation=value.generation;activity.current=value.activity??null;
   for(const entry of value.events??[]){if((entry.generation!==undefined&&entry.generation!==generation)||entry.kind!=='rpc'||!entry.event)continue;const e=entry.event;
    if(e.type==='message_start'||e.type==='message_update'||e.type==='message_end'){if(e.message&&typeof e.message==='object')upsert(e.message as Message)}
    if(e.type==='agent_start'&&!activity.current)setWorking(true);
    if(e.type==='agent_settled'||(e.type==='agent_end'&&!activity.current)){if(!activity.current)setWorking(false);setSending(false);if(hydrated){void rpc('get_messages').catch(()=>{});void rpc('get_state').catch(()=>{})}}
    if(e.type==='response'&&typeof e.id==='string'&&e.id.startsWith(prefix.current+':')){
     if(e.success===false){if(submitted.current.has(e.id)){try{sessionStorage.removeItem('pi-attachment-send:'+sessionId)}catch{}}setError(typeof e.error==='string'?e.error:'Agent 操作失败');setSending(false);submitted.current.delete(e.id);submittedAttachments.current.delete(e.id);if(['get_messages','get_state','get_available_models','get_commands'].includes(String(e.command)))hydrated=false;else void rpc('get_state').catch(()=>{});continue}
     const data=(e.data??{}) as Record<string,unknown>;
     if(e.command==='get_messages'&&Array.isArray(data.messages))setMessages(data.messages as Message[]);
     if(e.command==='get_available_models'&&Array.isArray(data.models))setModels(data.models as Model[]);
     if(e.command==='get_commands'&&Array.isArray(data.commands))setCommands((data.commands as PiCommand[]).filter(item=>typeof item.name==='string'&&['extension','prompt','skill'].includes(item.source)));
     if(e.command==='get_state'){if(!activity.current)setWorking(Boolean(data.isStreaming||data.isCompacting));setPending(Number(data.pendingMessageCount??0));if(data.model&&typeof data.model==='object'){const m=data.model as Model;setModel(JSON.stringify([m.provider,m.id]))}if(typeof data.thinkingLevel==='string')setThinking(data.thinkingLevel)}
     if(['prompt','steer','follow_up'].includes(String(e.command))){const original=submitted.current.get(e.id);submitted.current.delete(e.id);const sentFiles=submittedAttachments.current.get(e.id)??[];submittedAttachments.current.delete(e.id);try{sessionStorage.removeItem('pi-attachment-send:'+sessionId)}catch{}setAttachments(current=>current.filter(file=>!sentFiles.includes(file.agent_path)));setInput(current=>current===original?'':current);setSending(false);void rpc('get_state').catch(()=>{})}
     if(e.command==='set_model'||e.command==='set_thinking_level'||e.command==='abort'||e.command==='compact')void rpc('get_state').catch(()=>{});
    }
   }
   if(activity.current)setWorking(activity.current.busy);
   cursor=value.next??cursor;
   if(live&&value.mode==='rpc'&&(!hydrated||value.gap)){await hydrate();hydrated=true}
   if(!live){hydrated=false;setWorking(false);if(!starting.current){setSending(false);if(submitted.current.size){submitted.current.clear();submittedAttachments.current.clear();setError('环境已停止，上一条消息的接收状态未知，请恢复后检查历史。')}}}
  }catch(e){if(!disposed)setError(e instanceof Error?e.message:'连接中断，正在重新连接')}finally{if(!disposed)timer=setTimeout(poll,live?500:1800)}};
  void poll();return()=>{disposed=true;clearTimeout(timer)};
 // Session is keyed by its immutable identifier; polling owns its stream cursor.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[sessionId]);
 async function connect(){setError('');starting.current=true;try{await op('start',{mode:'rpc'});setRunning(true);setMode('rpc')}finally{starting.current=false}}
 async function upload(files:File[]){
  if(!files.length)return;
  if(uploadLock.current||sending){setError('请等待当前上传或消息发送完成。');return}
  uploadLock.current=true;setUploading(true);setError('');const controller=new AbortController();uploadController.current=controller;
  const failures:string[]=[];
  try{for(const file of files){if(controller.signal.aborted)break;try{
   setUploadProgress(`${file.name} · 0%`);
   const done=await uploadFile(sessionId,file,percent=>{if(!controller.signal.aborted)setUploadProgress(`${file.name} · ${percent}%`)},controller.signal);
   if(controller.signal.aborted)break;
   setAttachments(current=>[...current.filter(item=>item.agent_path!==done.agent_path),done]);
  }catch(cause){failures.push(`${file.name}：${cause instanceof Error?cause.message:'上传失败'}`)}}
  if(failures.length&&!controller.signal.aborted)setError(failures.join('；'));
  }finally{uploadLock.current=false;if(!controller.signal.aborted){setUploading(false);setUploadProgress('')}}
 }
 async function submit(){
  const draft=input;const selected=attachments;const text=input.trim();
  if((!text&&!selected.length)||sending||uploadLock.current)return;
  setSending(true);setError('');attachmentSnapshot.current=selected.map(file=>file.agent_path);try{sessionStorage.setItem('pi-attachment-send:'+sessionId,JSON.stringify(attachmentSnapshot.current))}catch{}
  const message=[text||'请查看上传的文件。',...(selected.length?['','附件（已上传）：',...selected.map(file=>`- ${JSON.stringify(file.name)}：${JSON.stringify(file.agent_path)}`)]:[])].join('\n');
  try{if(!running)await connect();else if(mode!=='rpc')throw new Error('此会话正在辅助终端运行，请先结束终端环境再继续对话。');
   const extension=commands.some(command=>command.source==='extension'&&text.split(/\s/,1)[0]==='/'+command.name);
   await rpc(working&&!extension?queueMode:'prompt',{message},draft);setCommandsOpen(false)
  }catch(e){setError(e instanceof Error?e.message:'发送失败');setSending(false)}
 }
 async function action(type:string,params:Record<string,unknown>={}){setError('');try{await rpc(type,params)}catch(e){setError(e instanceof Error?e.message:'操作失败')}}
 return <div className='relative' onDragEnter={event=>{if(event.dataTransfer.types.includes('Files')){event.preventDefault();dragDepth.current++;setDragging(true)}}} onDragOver={event=>{if(event.dataTransfer.types.includes('Files')){event.preventDefault();event.dataTransfer.dropEffect=uploading||sending?'none':'copy'}}} onDragLeave={event=>{if(event.dataTransfer.types.includes('Files')){event.preventDefault();dragDepth.current=Math.max(0,dragDepth.current-1);if(!dragDepth.current)setDragging(false)}}} onDrop={event=>{if(!event.dataTransfer.types.includes('Files'))return;event.preventDefault();dragDepth.current=0;setDragging(false);if(Array.from(event.dataTransfer.items).some(item=>item.webkitGetAsEntry?.()?.isDirectory)){setError('请拖入文件；文件夹请先压缩后上传。');return}void upload(Array.from(event.dataTransfer.files))}}>
  {dragging&&<div className='pointer-events-none absolute inset-0 z-30 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/95'><p className='text-primary text-lg font-medium'>{uploading||sending?'请等待当前操作完成':'松开即可上传文件'}</p></div>}
  <section className={styles.shell} aria-label='AI 助手'>
   <header className={styles.header}>{controls}<details className={styles.menu}><summary className={styles.iconButton} aria-label='会话设置' title='会话设置'><IconAdjustmentsHorizontal size={18}/></summary><div className={styles.menuPanel}>
    {working&&<button onClick={()=>void action('abort')}>中断回复</button>}
    <button disabled={!running||working} onClick={()=>void action('compact')}>整理上下文</button>
    {!running&&<button onClick={()=>void connect().catch(e=>setError(e.message))}>恢复会话环境</button>}
    <button disabled={!running} onClick={()=>void op('stop').then(()=>{setRunning(false);setWorking(false);setSending(false)}).catch(e=>setError(e.message))}>结束会话环境</button>
   </div></details></header>
   {error&&<div role='alert' className='text-destructive mx-3 flex max-h-24 shrink-0 justify-between gap-2 overflow-y-auto rounded-lg border p-3 text-sm'>{error}<button aria-label='关闭错误提示' onClick={()=>setError('')}><IconX size={16}/></button></div>}
   <div ref={viewport} role='region' aria-label='Agent 对话消息' className={styles.viewport} onScroll={()=>{const el=viewport.current;if(el)follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<100}}><div className={styles.stream}>
    {!messages.length&&<div className={styles.empty}><h2>今天想完成什么？</h2><p>描述任务，或上传文件开始工作。</p><div className={styles.suggestions}>{['分析上传的表格','查看可用工具','帮我整理文件'].map(text=><button key={text} onClick={()=>{setInput(text);composer.current?.focus()}}>{text}</button>)}</div></div>}
    <PiChatMessages messages={messages} sessionId={sessionId}/>
    <PiChatArtifacts sessionId={sessionId} busy={working} revision={`${messages.length}:${messages.at(-1)?.timestamp??0}`}/>
   </div></div>
   <div className={styles.composerArea}>
    {(working||sending||pending>0)&&<div className={styles.status} role='status'><span className={styles.pulse}/>{sending?'正在发送…':working?'正在处理…':'等待继续'}{pending>0?` · ${pending} 条待处理`:''}</div>}
    <div className='relative'>
     {commandsOpen&&<PiCommands commands={commands} query={input.startsWith('/')&&!input.trimStart().includes(' ')?input.slice(1):''} onChoose={command=>{setInput('/'+command.name+' ');setCommandsOpen(false);composer.current?.focus()}} onClose={()=>setCommandsOpen(false)} onRefresh={()=>void action('get_commands')}/>}
     <div className={styles.composer}>
      <input ref={picker} type='file' multiple className='hidden' aria-label='上传聊天附件' disabled={uploading||sending} onChange={event=>{void upload(Array.from(event.target.files??[]));event.target.value=''}}/>
      {(attachments.length>0||uploading)&&<div className={styles.attachments} aria-label='待发送附件'>{attachments.map(file=><span key={file.agent_path} className={styles.attachment}><span>{file.name}</span><button type='button' disabled={sending} aria-label={`移除附件 ${file.name}`} onClick={()=>setAttachments(current=>current.filter(item=>item.agent_path!==file.agent_path))}><IconX size={14}/></button></span>)}{uploading&&<span role='status' className='text-muted-foreground text-xs'>{uploadProgress}</span>}</div>}
      <textarea ref={composer} aria-label='给 Agent 的任务' value={input} onChange={e=>{setInput(e.target.value);setCommandsOpen(e.target.value.startsWith('/')&&!/\s/.test(e.target.value))}} onKeyDown={e=>{if(e.key==='Escape'){setCommandsOpen(false);return}if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void submit()}}} placeholder='描述任务，或将文件拖到这里…' className={styles.input} rows={3}/>
      <div className={styles.toolbar}><div className={styles.toolbarLeft}>
       <button type='button' className={styles.iconButton} aria-label='上传文件' title='上传文件' disabled={uploading||sending} onClick={()=>picker.current?.click()}><IconPlus size={19}/></button>
       <button type='button' className={styles.chip} aria-label='选择 Skill、模板或扩展命令' aria-expanded={commandsOpen} onClick={()=>{setCommandsOpen(value=>!value);if(running)void action('get_commands')}}>/ 命令</button>
       <select aria-label='Agent 模型' value={model} disabled={!running||working} onChange={e=>{const [provider,modelId]=JSON.parse(e.target.value);void action('set_model',{provider,modelId})}} className={styles.chip}><option value='' disabled>默认模型</option>{models.map(item=><option key={JSON.stringify([item.provider,item.id])} value={JSON.stringify([item.provider,item.id])}>{item.name??item.id}</option>)}</select>
       <select aria-label='思考强度' value={thinking} disabled={!running||working} onChange={e=>void action('set_thinking_level',{level:e.target.value})} className={styles.chip}>{Object.entries({off:'关闭推理',minimal:'最少推理',low:'低推理',medium:'中等推理',high:'高推理',xhigh:'更高推理',max:'最高推理'}).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select>
       {working&&<select aria-label='运行时消息处理方式' value={queueMode} onChange={e=>setQueueMode(e.target.value)} className={styles.chip}><option value='follow_up'>完成后继续</option><option value='steer'>调整当前任务</option></select>}
      </div>{working&&!input.trim()&&!attachments.length?<button className={styles.send} aria-label='中断回复' title='中断回复' onClick={()=>void action('abort')}><IconSquare size={13} fill='currentColor'/></button>:<button className={styles.send} aria-label={sending?'发送中':working?'发送补充':'发送消息'} title={working?'发送补充':'发送消息'} disabled={sending||uploading||(!input.trim()&&!attachments.length)} onClick={()=>void submit()}><IconArrowUp size={19}/></button>}</div>
     </div>
    </div><p className={styles.caption}>Enter 发送 · Shift+Enter 换行</p>
   </div>
  </section>
  {dialogs.length>0&&<div className='bg-background fixed right-4 bottom-4 z-40 max-h-[70dvh] w-[min(32rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border p-4 shadow-xl'><PiDialogs requests={dialogs} reply={command=>op('send',{command})}/></div>}
 </div>;}
export function PiChat({initialSessions,initialSessionId,skillId}:{initialSessions:PiSession[];initialSessionId?:string;skillId?:string}){
 const history=useRef<HTMLDialogElement>(null);
 const [sessions,setSessions]=useState(initialSessions);const [selected,setSelected]=useState(initialSessions.some(item=>item.id===initialSessionId)?initialSessionId!:initialSessions[0]?.id??'');const [error,setError]=useState('');const [creating,setCreating]=useState(false);
 useEffect(()=>{const url=new URL(window.location.href);if(selected)url.searchParams.set('session',selected);else url.searchParams.delete('session');window.history.replaceState(null,'',url)},[selected]);
 async function create(){setCreating(true);setError('');try{const item=await api<PiSession>('/sessions',{channel:'assistant',title:skillId?`${skillId} 对话`:'新对话',...(skillId?{skill_id:skillId}:{})});setSessions(old=>[item,...old]);setSelected(item.id)}catch(e){setError(e instanceof Error?e.message:'创建失败')}finally{setCreating(false)}}
 const controls=<div className={styles.controls}><button className={styles.iconButton} aria-label='打开会话列表' title='会话列表' onClick={()=>history.current?.showModal()}><IconLayoutSidebar size={19}/></button><h1 className={styles.title}>{sessions.find(item=>item.id===selected)?.title||'AI 助手'}</h1><button className={styles.iconButton} aria-label='新建对话' title='新建对话' disabled={creating} onClick={()=>void create()}><IconEdit size={19}/></button></div>;
 return <div className='min-w-0'>
  <dialog ref={history} className={styles.history} aria-label='会话列表'><div className='flex items-center justify-between px-2'><h2 className='text-sm font-medium'>会话</h2><button className={styles.iconButton} aria-label='关闭会话列表' onClick={()=>history.current?.close()}><IconX size={18}/></button></div><div className={styles.historyList}>{sessions.map(item=><button key={item.id} className={styles.historyItem} aria-current={item.id===selected?'true':undefined} onClick={()=>{setSelected(item.id);history.current?.close()}}><span>{item.title}</span><small>{item.id.slice(0,8)}</small></button>)}{!sessions.length&&<p className='text-muted-foreground p-3 text-sm'>尚无会话</p>}</div></dialog>
  {error&&<p role='alert'>{error}</p>}
  {selected?<ChatSession key={selected} sessionId={selected} controls={controls}/>:<section className={styles.shell}><header className={styles.header}>{controls}</header><div className={styles.stream}><div className={styles.empty}><h2>今天想完成什么？</h2><p>新建对话，开始使用 AI 助手。</p><div className={styles.suggestions}><button disabled={creating} onClick={()=>void create()}>新建对话</button></div></div></div></section>}
 </div>;
}
