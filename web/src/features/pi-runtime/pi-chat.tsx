'use client';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {useRouter} from 'next/navigation';
import {IconArrowUp,IconSquare,IconPlus,IconAdjustmentsHorizontal,IconLayoutSidebar,IconEdit,IconX} from '@tabler/icons-react';
import {PiChatMessages} from './pi-chat-messages';
import {DeerflowMessages} from './deerflow/deerflow-messages';
import {DeerflowWelcome} from './deerflow/deerflow-conversation';
import styles from './pi-chat-design.module.css';
import {PiCommands} from './pi-commands';
import {PiChatArtifacts} from './pi-chat-artifacts';
import {PiDialogs} from './pi-dialogs';
import {piRequest} from './pi-client';
import {usePiSession} from './use-pi-session';
import {deliveryMessage} from './pi-delivery-view';
import type {PiSession} from './pi-workspace';
import {SessionEnvironments} from './session-environments';

function ChatSession({sessionId,storageScope,controls}:{sessionId:string;storageScope:string;controls:ReactNode}){
 const composer=useRef<HTMLTextAreaElement>(null);
 const {view,actions}=usePiSession({sessionId,storageScope});
 const {interrupting,controlNotice,artifacts,status,connectionError,commands,commandsOpen,messages,input,error,running,working,sending,queueMode,models,model,thinking,pending,dialogs,delivery,uncertainDelivery,uploading,uploadProgress,attachments}=view;
 const {refreshArtifacts,setCommandsOpen,setInput,setError,setQueueMode,setAttachments,queryDelivery,connect,upload,submit,acknowledgeDelivery,closeEnvironment,changeModel,interruptReply,takeQueuedMessages,compactContext,refreshCommands,changeThinking,replyToDialog}=actions;
 const [interruptChoice,setInterruptChoice]=useState(false);
 const [renderer]=useState(()=>{if(typeof window==='undefined')return '';try{const param=new URLSearchParams(window.location.search).get('renderer');if(param)return param;return localStorage.getItem('pi-renderer')??''}catch{return ''}});
 const picker=useRef<HTMLInputElement>(null);const viewport=useRef<HTMLDivElement>(null);const follow=useRef(true);
 const dragDepth=useRef(0);const [dragging,setDragging]=useState(false);
 useEffect(()=>{const el=composer.current;if(el){el.style.height='auto';el.style.height=Math.min(192,Math.max(96,el.scrollHeight))+'px'}},[input]);
 useEffect(()=>{if(follow.current&&viewport.current)viewport.current.scrollTop=viewport.current.scrollHeight},[messages]);
 useEffect(()=>{const el=viewport.current;if(!el)return;const observer=new ResizeObserver(()=>{if(follow.current)el.scrollTop=el.scrollHeight});for(const child of Array.from(el.children))observer.observe(child);const mutation=new MutationObserver(()=>{for(const child of Array.from(el.children))observer.observe(child);if(follow.current)el.scrollTop=el.scrollHeight});mutation.observe(el,{childList:true});return()=>{observer.disconnect();mutation.disconnect()}},[]);
 return <div className='relative' onDragEnter={event=>{if(event.dataTransfer.types.includes('Files')){event.preventDefault();dragDepth.current++;setDragging(true)}}} onDragOver={event=>{if(event.dataTransfer.types.includes('Files')){event.preventDefault();event.dataTransfer.dropEffect=uploading||sending?'none':'copy'}}} onDragLeave={event=>{if(event.dataTransfer.types.includes('Files')){event.preventDefault();dragDepth.current=Math.max(0,dragDepth.current-1);if(!dragDepth.current)setDragging(false)}}} onDrop={event=>{if(!event.dataTransfer.types.includes('Files'))return;event.preventDefault();dragDepth.current=0;setDragging(false);if(Array.from(event.dataTransfer.items).some(item=>item.webkitGetAsEntry?.()?.isDirectory)){setError('请拖入文件；文件夹请先压缩后上传。');return}void upload(Array.from(event.dataTransfer.files))}}>
  {dragging&&<div className='pointer-events-none absolute inset-0 z-30 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/95'><p className='text-primary text-lg font-medium'>{uploading||sending?'请等待当前操作完成':'松开即可上传文件'}</p></div>}
  <section className={styles.shell} aria-label='AI 助手'>
   <header className={styles.header}>{controls}<details className={styles.menu}><summary className={styles.iconButton} aria-label='会话设置' title='会话设置'><IconAdjustmentsHorizontal size={18}/></summary><div className={styles.menuPanel}>
    {working&&<button disabled={!status.canInterrupt} onClick={()=>setInterruptChoice(true)}>中断回复</button>}
    <button disabled={!status.canConfigure} onClick={()=>void compactContext()}>整理上下文</button>
    {!running&&<button disabled={!status.canStartEnvironment} onClick={()=>void connect().catch(e=>setError(e.message))}>恢复会话环境</button>}
    <button disabled={!running||!status.canManageEnvironment} onClick={()=>void closeEnvironment()}>结束会话环境</button>
    <button onClick={()=>{try{localStorage.setItem('pi-renderer',renderer==='deerflow'?'':'deerflow')}catch{/* ignore */}window.location.reload()}}>切换展示样式（当前：{renderer==='deerflow'?'新版':'经典'}）</button>
   </div></details></header>
   {status.message&&<p role='status' title={connectionError||undefined} className='text-muted-foreground mx-3 rounded-lg border p-2 text-sm'>{status.message}</p>}
   {controlNotice&&<p role='status' className='mx-3 rounded-lg border p-2 text-sm'>{controlNotice}</p>}
   {interruptChoice&&<div role='dialog' aria-label='中断回复选项' className='mx-3 rounded-lg border p-3 text-sm'><p>仅影响当前 Agent 回复。后台任务和财务任务需要分别停止；排队消息可能随下一次回复继续。</p><div className='mt-2 flex flex-wrap gap-3'><button disabled={!status.canInterrupt||interrupting} onClick={()=>{setInterruptChoice(false);void interruptReply(false)}}>仅中断，保留排队消息</button><button disabled={!status.canInterrupt||interrupting} onClick={()=>{setInterruptChoice(false);void interruptReply(true)}}>清空排队消息并中断</button><button onClick={()=>setInterruptChoice(false)}>返回对话</button></div></div>}
   {error&&<div role='alert' className='text-destructive mx-3 flex max-h-24 shrink-0 justify-between gap-2 overflow-y-auto rounded-lg border p-3 text-sm'>{error}<button aria-label='关闭错误提示' onClick={()=>setError('')}><IconX size={16}/></button></div>}
   {delivery&&<div role='status' className='mx-3 flex flex-wrap items-center gap-2 rounded-lg border p-2 text-sm'>{deliveryMessage(delivery.state)}{uncertainDelivery&&delivery.state!=='submitting'&&<><button type='button' className='underline' onClick={()=>void queryDelivery(delivery.id)}>查询投递状态</button><button type='button' className='underline' onClick={acknowledgeDelivery}>已核对，准备新请求</button></>}</div>}
   <div ref={viewport} role='region' aria-label='Agent 对话消息' className={styles.viewport} onScroll={()=>{const el=viewport.current;if(el)follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<100}}><div className={styles.stream}>
    {!messages.length&&(renderer==='deerflow'?<DeerflowWelcome greeting='今天想完成什么？' description='描述任务，或上传文件开始工作。' suggestions={['分析上传的表格','查看可用工具','帮我整理文件']} onPick={text=>{setInput(text);composer.current?.focus()}}/>:<div className={styles.empty}><h2>今天想完成什么？</h2><p>描述任务，或上传文件开始工作。</p><div className={styles.suggestions}>{['分析上传的表格','查看可用工具','帮我整理文件'].map(text=><button key={text} onClick={()=>{setInput(text);composer.current?.focus()}}>{text}</button>)}</div></div>)}
    {renderer==='deerflow'?<DeerflowMessages messages={messages} sessionId={sessionId}/>:<PiChatMessages messages={messages} sessionId={sessionId}/>}
    <PiChatArtifacts view={artifacts} onRefresh={refreshArtifacts}/>
   </div></div>
   <div className={styles.composerArea}>
    {(status.executionState==='running'||status.executionState==='waiting_input'||sending||pending>0)&&<div className={styles.status} role='status'><span className={styles.pulse}/>{status.activityLabel}{pending>0?` · ${pending} 条待处理`:''}{pending>0&&<button type='button' className='ml-2 underline' disabled={!status.canTakeQueue} onClick={()=>void takeQueuedMessages()}>取回排队消息</button>}</div>}
    <div className='relative'>
     {commandsOpen&&<PiCommands commands={commands} query={input.startsWith('/')&&!input.trimStart().includes(' ')?input.slice(1):''} onChoose={command=>{setInput('/'+command.name+' ');setCommandsOpen(false);composer.current?.focus()}} onClose={()=>setCommandsOpen(false)} onRefresh={()=>void refreshCommands()}/>}
     <div className={styles.composer}>
      <input ref={picker} type='file' multiple className='hidden' aria-label='上传聊天附件' disabled={!status.canUpload||uploading||sending} onChange={event=>{void upload(Array.from(event.target.files??[]));event.target.value=''}}/>
      {(attachments.length>0||uploading)&&<div className={styles.attachments} aria-label='待发送附件'>{attachments.map(file=><span key={file.agent_path} className={styles.attachment}><span>{file.name}</span><button type='button' disabled={sending} aria-label={`移除附件 ${file.name}`} onClick={()=>setAttachments(current=>current.filter(item=>item.agent_path!==file.agent_path))}><IconX size={14}/></button></span>)}{uploading&&<span role='status' className='text-muted-foreground text-xs'>{uploadProgress}</span>}</div>}
      <textarea ref={composer} aria-label='给 Agent 的任务' value={input} onChange={e=>{setInput(e.target.value);setCommandsOpen(e.target.value.startsWith('/')&&!/\s/.test(e.target.value))}} onKeyDown={e=>{if(e.key==='Escape'){setCommandsOpen(false);return}if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void submit()}}} placeholder='描述任务，或将文件拖到这里…' className={styles.input} rows={3}/>
      <div className={styles.toolbar}><div className={styles.toolbarLeft}>
       <button type='button' className={styles.iconButton} aria-label='上传文件' title='上传文件' disabled={!status.canUpload||uploading||sending} onClick={()=>picker.current?.click()}><IconPlus size={19}/></button>
       <button type='button' className={styles.chip} aria-label='选择 Skill、模板或扩展命令' aria-expanded={commandsOpen} disabled={!status.canListCommands} onClick={()=>{setCommandsOpen(value=>!value);if(running)void refreshCommands()}}>/ 命令</button>
       <select aria-label='当前会话模型' title='仅切换当前会话使用的模型' value={model} disabled={!status.canConfigure} onChange={e=>changeModel(e.target.value)} className={styles.chip}><option value='' disabled>{running?'正在读取会话模型':'启动会话后可切换'}</option>{models.map(item=><option key={JSON.stringify([item.provider,item.id])} value={JSON.stringify([item.provider,item.id])}>{item.name??item.id}</option>)}</select>
       <select aria-label='思考强度' value={thinking} disabled={!status.canConfigure} onChange={e=>void changeThinking(e.target.value)} className={styles.chip}>{Object.entries({off:'关闭推理',minimal:'最少推理',low:'低推理',medium:'中等推理',high:'高推理',xhigh:'更高推理',max:'最高推理'}).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select>
       {working&&<select aria-label='运行时消息处理方式' value={queueMode} onChange={e=>setQueueMode(e.target.value)} className={styles.chip}><option value='follow_up'>完成后继续</option><option value='steer'>调整当前任务</option></select>}
      </div>{working&&!input.trim()&&!attachments.length?<button disabled={!status.canInterrupt} className={styles.send} aria-label='中断回复' title='中断回复' onClick={()=>setInterruptChoice(true)}><IconSquare size={13} fill='currentColor'/></button>:<button className={styles.send} aria-label={status.submitLabel} title={working?'发送补充':'发送消息'} disabled={!status.canSend||(!input.trim()&&!attachments.length)} onClick={()=>void submit()}><IconArrowUp size={19}/></button>}</div>
     </div>
    </div><p className={styles.caption}>Enter 发送 · Shift+Enter 换行</p>
   </div>
  </section>
  {dialogs.length>0&&<div className='bg-background fixed right-4 bottom-4 z-40 max-h-[70dvh] w-[min(32rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border p-4 shadow-xl'><PiDialogs requests={dialogs} available={status.canReplyToDialog} allowApproval={status.canApproveInput} reply={replyToDialog}/></div>}
 </div>;}
export function PiChat({initialSessions,initialSessionId,skillId,modelSettings,storageScope}:{initialSessions:PiSession[];initialSessionId?:string;skillId?:string;modelSettings?:ReactNode;storageScope:string}){
 const router=useRouter();
 const history=useRef<HTMLDialogElement>(null);
 const [sessions,setSessions]=useState(initialSessions);const [selected,setSelected]=useState(initialSessions.some(item=>item.id===initialSessionId)?initialSessionId!:initialSessions[0]?.id??'');const [error,setError]=useState('');const [creating,setCreating]=useState(false);
 useEffect(()=>{if(initialSessionId&&initialSessions.some(item=>item.id===initialSessionId))setSelected(initialSessionId)},[initialSessionId,initialSessions]);
 useEffect(()=>{const url=new URL(window.location.href);if(selected)url.searchParams.set('session',selected);else url.searchParams.delete('session');if(url.href!==window.location.href)router.replace(url.pathname+url.search+url.hash,{scroll:false})},[selected,router]);
 async function create(){setCreating(true);setError('');try{const item=await piRequest<PiSession>('/sessions',{channel:'assistant',title:skillId?`${skillId} 对话`:'新对话',...(skillId?{skill_id:skillId}:{})});setSessions(old=>[item,...old]);setSelected(item.id)}catch(e){setError(e instanceof Error?e.message:'创建失败')}finally{setCreating(false)}}
 const controls=<div className={`${styles.controls} flex-1 flex-wrap`}><button className={styles.iconButton} aria-label='打开会话列表' title='会话列表' onClick={()=>history.current?.showModal()}><IconLayoutSidebar size={19}/></button><h1 className={styles.title}>{sessions.find(item=>item.id===selected)?.title||'AI 助手'}</h1><button className={styles.iconButton} aria-label='新建对话' title='新建对话' disabled={creating} onClick={()=>void create()}><IconEdit size={19}/></button><SessionEnvironments currentSessionId={selected}/>{modelSettings&&<div className="ml-auto">{modelSettings}</div>}</div>;
 return <div className='min-w-0'>
  <dialog ref={history} className={styles.history} aria-label='会话列表'><div className='flex items-center justify-between px-2'><h2 className='text-sm font-medium'>会话</h2><button className={styles.iconButton} aria-label='关闭会话列表' onClick={()=>history.current?.close()}><IconX size={18}/></button></div><div className={styles.historyList}>{sessions.map(item=><button key={item.id} className={styles.historyItem} aria-current={item.id===selected?'true':undefined} onClick={()=>{setSelected(item.id);history.current?.close()}}><span>{item.title}</span><small>{item.id.slice(0,8)}</small></button>)}{!sessions.length&&<p className='text-muted-foreground p-3 text-sm'>尚无会话</p>}</div></dialog>
  {error&&<p role='alert'>{error}</p>}
  {selected?<ChatSession key={storageScope+':'+selected} sessionId={selected} storageScope={storageScope} controls={controls}/>:<section className={styles.shell}><header className={styles.header}>{controls}</header><div className={styles.stream}><div className={styles.empty}><h2>今天想完成什么？</h2><p>新建对话，开始使用 AI 助手。</p><div className={styles.suggestions}><button disabled={creating} onClick={()=>void create()}>新建对话</button></div></div></div></section>}
 </div>;
}
