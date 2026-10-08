'use client';
import {useEffect,useRef,useState} from 'react';
import {createClientId} from '@/lib/client-id';
import {messageKey as key,type ChatMessage as Message} from './pi-chat-messages';
import type {PiCommand} from './pi-commands';
import {uploadFile,type UploadedFile} from './pi-file-transfer';
import {validatePiDialogReply,type PiDialog} from './pi-dialog-gate';
import {piRequest} from './pi-client';
import {PiStartObservation} from './pi-start-observation';
import {PiObservationLoop,piObservationDelay} from './pi-observation-loop';
import {checkedPiCapabilities,applyPiCapabilities,permitsPiDialogResponse,type PiSessionCapabilities} from './pi-capabilities';
import {applyTransportReceipt,markDeliveryUncertain,deliveryUnconfirmed,type PiDeliveryView} from './pi-delivery-view';
import {PiControlRequests,interruptPiReply,queueMessages,takePiQueuedMessages,type ControlType} from './pi-control-requests';
import {usePiArtifacts} from './use-pi-artifacts';
import {projectPiSessionStatus,type PiConnectionState} from './pi-view-model';
import type {PiDeliveryReceipt,PiModel as Model,PiPoll as Poll} from './pi-protocol';
import {reducePiPoll} from './pi-event-reducer';
import {readPiStorage,writePiStorage,removePiStorage} from './pi-storage';

/** Own observations, delivery and drafts; unmount only cancels observations. */
export function usePiSession({sessionId,storageScope}:{sessionId:string;storageScope:string}){
 const controlRequests=useRef(new PiControlRequests());const interruptLock=useRef(false);const [interrupting,setInterrupting]=useState(false);const [controlNotice,setControlNotice]=useState('');
 const [connection,setConnection]=useState<PiConnectionState>('connecting');const [connectionError,setConnectionError]=useState('');const [activityKnown,setActivityKnown]=useState(false);
 const [commands,setCommands]=useState<PiCommand[]>([]);const [commandsOpen,setCommandsOpen]=useState(false);
 const [messages,setMessages]=useState<Message[]>([]);const [input,setInput]=useState('');const [error,setError]=useState('');
 const [running,setRunning]=useState(false);const [mode,setMode]=useState('');const [working,setWorking]=useState(false);const [sending,setSending]=useState(false);const [queueMode,setQueueMode]=useState('follow_up');
 const [models,setModels]=useState<Model[]>([]);const [model,setModel]=useState('');const [thinking,setThinking]=useState('high');const [pending,setPending]=useState(0);
 const [dialogs,setDialogs]=useState<PiDialog[]>([]);
 const dialogObservation=useRef(false);
 const startObservation=useRef(new PiStartObservation());const pollSequence=useRef(0);const sessionActive=useRef(false);const [connectingEnvironment,setConnectingEnvironment]=useState(false);
 const capabilitiesRef=useRef<PiSessionCapabilities|null>(null);const [capabilities,setCapabilities]=useState<PiSessionCapabilities|null>(null);
 const activeDeliveryRequest=useRef<string|null>(null);const piReplies=useRef(new Set<string>());
 const [delivery,setDelivery]=useState<PiDeliveryView|null>(null);
 const uncertainDelivery=deliveryUnconfirmed(delivery);
 const rememberPiReply=(requestId:string)=>{piReplies.current.add(requestId);if(piReplies.current.size>32)piReplies.current.delete(piReplies.current.values().next().value!)};
 const queryDelivery=async(requestId:string,signal?:AbortSignal)=>{try{const receipt=await piRequest<PiDeliveryReceipt>(`/sessions/${encodeURIComponent(sessionId)}/deliveries/${encodeURIComponent(requestId)}`,undefined,signal);setDelivery(current=>applyTransportReceipt(current,receipt))}catch(cause){if(!(cause instanceof DOMException&&cause.name==='AbortError'))setDelivery(current=>markDeliveryUncertain(current,requestId))}};
 useEffect(()=>{let requestId:string|null=null;try{requestId=readPiStorage('delivery',storageScope,sessionId)}catch{}if(!requestId)return;activeDeliveryRequest.current=requestId;const controller=new AbortController();setDelivery({id:requestId,state:'unknown'});void queryDelivery(requestId,controller.signal);return()=>controller.abort();
 // The session component is remounted for every distinct session ID.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[sessionId,storageScope]);
 const uploadController=useRef<AbortController|null>(null);
 const inputSnapshot=useRef(input);inputSnapshot.current=input;
 const [draftsLoaded,setDraftsLoaded]=useState(false);
 useEffect(()=>{try{setInput(readPiStorage('text-draft',storageScope,sessionId)??'');const saved=JSON.parse(readPiStorage('attachments',storageScope,sessionId)??'[]');const pendingFiles=JSON.parse(readPiStorage('attachment-send',storageScope,sessionId)??'[]');const uncertain=Array.isArray(pendingFiles)?pendingFiles:[];if(uncertain.length)setError('上一条附件消息的接收状态待核实，请先查看聊天记录，避免重复发送。');if(Array.isArray(saved))setAttachments(saved.filter((file:UploadedFile)=>file&&typeof file.name==='string'&&typeof file.agent_path==='string'&&file.agent_path.startsWith('/inputs/')&&!uncertain.includes(file.agent_path)))}catch{}setDraftsLoaded(true);return()=>{uploadController.current?.abort()}},[sessionId,storageScope]);const uploadLock=useRef(false);
 const [uploading,setUploading]=useState(false);const [uploadProgress,setUploadProgress]=useState('');
 const [attachments,setAttachments]=useState<UploadedFile[]>([]);
 useEffect(()=>{if(draftsLoaded){try{writePiStorage('attachments',storageScope,sessionId,JSON.stringify(attachments))}catch{}}},[attachments,storageScope,sessionId,draftsLoaded]);
 useEffect(()=>{if(!draftsLoaded)return;try{if(input)writePiStorage('text-draft',storageScope,sessionId,input);else removePiStorage('text-draft',storageScope,sessionId)}catch{setError('文字草稿未能保存，离开页面前请复制保留。')}},[input,draftsLoaded,storageScope,sessionId]);
 const submittedAttachments=useRef(new Map<string,string[]>());const attachmentSnapshot=useRef<string[]>([]);
 const activity=useRef<{busy:boolean;phase:string}|null>(null);
 const submitted=useRef(new Map<string,string>());const submittedRequests=useRef(new Map<string,string>());const starting=useRef(false);
 const prefix=useRef(createClientId());
 const op=<T,>(operation:string,payload:unknown={},signal?:AbortSignal)=>piRequest<T>(`/sessions/${encodeURIComponent(sessionId)}/operate`,{operation,payload},signal);
 const rpc=(type:string,params:Record<string,unknown>={},originalDraft?:string,clientRequestId?:string)=>{const id=prefix.current+':'+type+':'+createClientId();if(['prompt','steer','follow_up'].includes(type)&&typeof params.message==='string'){submitted.current.set(id,originalDraft??params.message);submittedAttachments.current.set(id,attachmentSnapshot.current);if(clientRequestId)submittedRequests.current.set(id,clientRequestId)}return op<PiDeliveryReceipt>('send',{command:{...params,type,id},...(clientRequestId?{client_request_id:clientRequestId}:{})}).then(result=>{if(clientRequestId&&activeDeliveryRequest.current===clientRequestId&&!piReplies.current.has(clientRequestId)){setDelivery(current=>applyTransportReceipt(current,result));if(result.delivery_state!=='pi_accepted')setSending(false)}return result}).catch(cause=>{if(clientRequestId){if(activeDeliveryRequest.current!==clientRequestId||piReplies.current.has(clientRequestId))return;setDelivery(current=>markDeliveryUncertain(current,clientRequestId));setSending(false)}else{submitted.current.delete(id);submittedAttachments.current.delete(id)}throw cause})};
 useEffect(()=>{
  let disposed=false,cursor=0,instance='',generation:number|undefined,hydrated=false,historyLoaded=false,live=false,capabilitiesCheckedAt=0;let visibilityRevision=0;
  sessionActive.current=true;dialogObservation.current=false;setConnection('connecting');setActivityKnown(false);
  let pollController=new AbortController();
  const observe=(type:'get_messages'|'get_state'|'get_available_models'|'get_commands')=>
   op('send',{command:{type,id:prefix.current+':'+type+':'+createClientId()}},pollController.signal);
  const hydrate=async()=>{await observe('get_messages');await observe('get_state');if(capabilitiesRef.current?.can_configure){await observe('get_available_models');await observe('get_commands')}};
  const upsert=(message:Message)=>setMessages(old=>{const index=old.findIndex(item=>key(item)===key(message));return index<0?[...old,message]:old.map((item,i)=>i===index?message:item)});
  const poll=async()=>{if(pollController.signal.aborted)pollController=new AbortController();const observedVisibilityRevision=visibilityRevision;try{
   if(!capabilitiesRef.current||Date.now()-capabilitiesCheckedAt>15000){const policy=checkedPiCapabilities(await piRequest<unknown>(`/sessions/${encodeURIComponent(sessionId)}/capabilities`,undefined,pollController.signal),sessionId);if(disposed)return;if(JSON.stringify(policy)!==JSON.stringify(capabilitiesRef.current))hydrated=false;capabilitiesRef.current=policy;setCapabilities(policy);capabilitiesCheckedAt=Date.now();if(!policy.can_configure){setModels([]);setCommands([]);setCommandsOpen(false)}}
   const observationSequence=++pollSequence.current;const value=await op<Poll>('poll',{after:cursor},pollController.signal);if(disposed||observedVisibilityRevision!==visibilityRevision)return;
   live=value.running;setRunning(live);if(!live||value.activity)setActivityKnown(true);setMode(value.mode??'');setDialogs(value.pending_dialogs??[]);
   const reduced=reducePiPoll({cursor,instance,generation},value);
   if(reduced.reset){controlRequests.current.reset();dialogObservation.current=false;setActivityKnown(false);setConnection('connecting');cursor=reduced.cursor.cursor;hydrated=false;instance=reduced.cursor.instance;generation=reduced.cursor.generation;activity.current=null;setSending(false);if(submitted.current.size){submitted.current.clear();submittedRequests.current.clear();submittedAttachments.current.clear();setError('运行环境已变化，上一条消息的接收状态未知，请检查历史后再决定是否发送。')}return}
   cursor=reduced.cursor.cursor;instance=reduced.cursor.instance;generation=reduced.cursor.generation;activity.current=value.activity??null;
   for(const entry of reduced.events){if((entry.generation!==undefined&&entry.generation!==generation)||entry.kind!=='rpc'||!entry.event)continue;const e=entry.event;
    controlRequests.current.receive(e);
    if(e.type==='queue_update'){try{setPending(queueMessages(e).length)}catch{void observe('get_state').catch(()=>{})}}
    if(e.type==='message_start'||e.type==='message_update'||e.type==='message_end'){if(e.message&&typeof e.message==='object')upsert(e.message as Message)}
    if(e.type==='agent_start'&&!activity.current)setWorking(true);
    if(e.type==='agent_settled'||(e.type==='agent_end'&&!activity.current)){if(!activity.current)setWorking(false);setSending(false);if(hydrated){void observe('get_messages').catch(()=>{});void observe('get_state').catch(()=>{})}}
    if(e.type==='response'&&typeof e.id==='string'&&e.id.startsWith(prefix.current+':')){
     const eventRequestId=submittedRequests.current.get(e.id);const ownsDelivery=!eventRequestId||activeDeliveryRequest.current===eventRequestId;
     if(e.success===false){
      if(ownsDelivery&&submitted.current.has(e.id)){try{writePiStorage('text-draft',storageScope,sessionId,inputSnapshot.current);removePiStorage('attachment-send',storageScope,sessionId)}catch{}}
      if(eventRequestId){rememberPiReply(eventRequestId);submittedRequests.current.delete(e.id);if(ownsDelivery){setDelivery({id:eventRequestId,state:'rejected'});try{removePiStorage('delivery',storageScope,sessionId)}catch{}}}
      if(ownsDelivery){setError(typeof e.error==='string'?e.error:'Agent 操作失败');setSending(false)}
      submitted.current.delete(e.id);submittedAttachments.current.delete(e.id);if(['get_messages','get_state','get_available_models','get_commands'].includes(String(e.command)))hydrated=false;else void observe('get_state').catch(()=>{});continue
     }
     const data=(e.data??{}) as Record<string,unknown>;
     if(e.command==='get_messages'&&Array.isArray(data.messages))setMessages(data.messages as Message[]);
     if(e.command==='get_available_models'&&Array.isArray(data.models))setModels(data.models as Model[]);
     if(e.command==='get_commands'&&Array.isArray(data.commands))setCommands((data.commands as PiCommand[]).filter(item=>typeof item.name==='string'&&['extension','prompt','skill'].includes(item.source)));
     if(e.command==='get_state'){setActivityKnown(true);if(!activity.current)setWorking(Boolean(data.isStreaming||data.isCompacting));setPending(Number(data.pendingMessageCount??0));if(data.model&&typeof data.model==='object'){const m=data.model as Model;setModel(JSON.stringify([m.provider,m.id]))}if(typeof data.thinkingLevel==='string')setThinking(data.thinkingLevel)}
     if(['prompt','steer','follow_up'].includes(String(e.command))){
      if(eventRequestId){rememberPiReply(eventRequestId);submittedRequests.current.delete(e.id);if(ownsDelivery){setDelivery({id:eventRequestId,state:'pi_accepted'});try{removePiStorage('delivery',storageScope,sessionId)}catch{}}}
      const original=submitted.current.get(e.id);submitted.current.delete(e.id);const sentFiles=submittedAttachments.current.get(e.id)??[];submittedAttachments.current.delete(e.id);
      if(ownsDelivery){try{removePiStorage('attachment-send',storageScope,sessionId)}catch{}setAttachments(current=>current.filter(file=>!sentFiles.includes(file.agent_path)));setInput(current=>current===original?'':current);setSending(false)}
      void observe('get_state').catch(()=>{})
     }
     if(e.command==='set_model'||e.command==='set_thinking_level'||e.command==='abort'||e.command==='compact'||e.command==='clear_queue')void observe('get_state').catch(()=>{});
    }
   }
   if(activity.current)setWorking(activity.current.busy);
   if(live&&value.mode==='rpc'&&(!hydrated||reduced.gap)){await hydrate();hydrated=true}
   if(!live){hydrated=false;setWorking(false);if(!historyLoaded){historyLoaded=true;try{const saved=await piRequest<{messages:Message[];truncated:boolean}>(`/sessions/${encodeURIComponent(sessionId)}/history`,undefined,pollController.signal);if(!disposed){setMessages(saved.messages);if(saved.truncated)setError('历史消息过多，仅显示最近 500 条。')}}catch(cause){historyLoaded=false;throw cause}}if(!starting.current){setSending(false);if(submitted.current.size){submitted.current.clear();submittedRequests.current.clear();submittedAttachments.current.clear();setError('环境已停止，上一条消息的接收状态未知，请恢复后检查历史。')}}}else historyLoaded=false;
   if(!disposed&&observedVisibilityRevision===visibilityRevision){startObservation.current.observe(observationSequence,value,!reduced.gap);dialogObservation.current=true;setConnection('live');setConnectionError('')}
  }catch(e){if(!disposed&&observedVisibilityRevision===visibilityRevision){capabilitiesRef.current=null;setCapabilities(null);dialogObservation.current=false;setConnection('recovering');setConnectionError(e instanceof Error?e.message:'连接中断')}}};
  const loop=new PiObservationLoop(poll,()=>piObservationDelay(document.visibilityState!=='hidden',live));
  const visibilityChanged=()=>{if(document.visibilityState!=='hidden'){visibilityRevision++;hydrated=false;pollController.abort();dialogObservation.current=false;setActivityKnown(false);setConnection('recovering');loop.wake();}};
  document.addEventListener('visibilitychange',visibilityChanged);loop.wake();return()=>{disposed=true;document.removeEventListener('visibilitychange',visibilityChanged);loop.dispose();sessionActive.current=false;startObservation.current.cancel();controlRequests.current.reset();dialogObservation.current=false;pollController.abort()};
 // Session is keyed by its immutable identifier; polling owns its stream cursor.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[sessionId]);
 async function connect(){if(!capabilitiesRef.current?.can_start)throw new Error('当前会话没有开始新执行的权限。');if(starting.current)throw new Error('会话环境正在连接，请稍候。');dialogObservation.current=false;setError('');starting.current=true;setConnectingEnvironment(true);try{const started=await op<unknown>('start',{mode:'rpc'});if(!sessionActive.current)throw new Error('会话已切换，消息尚未发送。');setActivityKnown(false);setRunning(true);setMode('rpc');await startObservation.current.wait(started,pollSequence.current+1)}finally{starting.current=false;if(sessionActive.current)setConnectingEnvironment(false)}}
 async function upload(files:File[]){
  if(!files.length)return;
  if(!capabilitiesRef.current?.can_upload){setError('当前会话没有上传文件的权限。');return}
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
 const baseStatus=projectPiSessionStatus({connection,running,mode,working,activityKnown,dialogCount:dialogs.length,sending,uploading,uncertainDelivery:Boolean(uncertainDelivery)});
 const permittedStatus=applyPiCapabilities(baseStatus,capabilities);
 const status={...permittedStatus,canSend:permittedStatus.canSend&&!interrupting&&!connectingEnvironment,canConfigure:permittedStatus.canConfigure&&!interrupting,canInterrupt:permittedStatus.canInterrupt&&!interrupting,canManageEnvironment:permittedStatus.canManageEnvironment&&!interrupting,canStartEnvironment:permittedStatus.canStartEnvironment&&!interrupting&&!connectingEnvironment,canTakeQueue:connection==='live'&&activityKnown&&running&&mode==='rpc'&&pending>0&&!interrupting&&!connectingEnvironment&&!sending&&!uncertainDelivery};
 const artifacts=usePiArtifacts(sessionId,capabilities?.can_send===true&&connection==='live'&&(!running||activityKnown)&&!working,`${messages.length}:${messages.at(-1)?.timestamp??0}`);
 async function submit(){
  const draft=input;const selected=attachments;const text=input.trim();
  if((!text&&!selected.length)||!status.canSend||uploadLock.current||interruptLock.current)return;
  setSending(true);setError('');setControlNotice('');attachmentSnapshot.current=selected.map(file=>file.agent_path);
  const message=[text||'请查看上传的文件。',...(selected.length?['','附件（已上传）：',...selected.map(file=>`- ${JSON.stringify(file.name)}：${JSON.stringify(file.agent_path)}`)]:[])].join('\n');
  let requestId:string|undefined;
  try{if(!running)await connect();else if(mode!=='rpc')throw new Error('此会话正在辅助终端运行，请先结束终端环境再继续对话。');
   const extension=commands.some(command=>command.source==='extension'&&text.split(/\s/,1)[0]==='/'+command.name);
   const nextRequestId=createClientId();if(!writePiStorage('delivery',storageScope,sessionId,nextRequestId))throw new Error('会话缓存所属账号已变化，请刷新页面后再发送。');requestId=nextRequestId;activeDeliveryRequest.current=requestId;setDelivery({id:requestId,state:'submitting'});try{writePiStorage('attachment-send',storageScope,sessionId,JSON.stringify(attachmentSnapshot.current))}catch{}
   if(inputSnapshot.current===draft&&!removePiStorage('text-draft',storageScope,sessionId))throw new Error('会话缓存所属账号已变化，请刷新页面后再发送。');
   await rpc(working&&!extension?queueMode:'prompt',{message},draft,requestId);setCommandsOpen(false)
  }catch(e){setError(requestId?'投递状态尚未确认，请先查询回执和聊天历史，不要直接重复发送。':e instanceof Error?e.message:'发送失败');setSending(false)}
 }
 async function action(type:string,params:Record<string,unknown>={}){setError('');try{if(!capabilitiesRef.current?.rpc_commands.includes(type))throw new Error('当前会话没有执行此操作的权限。');await rpc(type,params)}catch(e){setError(e instanceof Error?e.message:'操作失败')}}
 const controlCommand=(type:ControlType)=>{if(!dialogObservation.current)return Promise.reject(new Error('会话观察已变化，控制结果待核实。'));const id=prefix.current+':'+type+':'+createClientId();return controlRequests.current.request(id,type,()=>op('send',{command:{type,id}}))};
 const restoreQueuedDraft=(messages:string[])=>{if(messages.length)setInput(current=>[current,...messages].filter(Boolean).join('\n\n'))};
 async function takeQueuedMessages(){
  if(!status.canTakeQueue||interruptLock.current)return;
  interruptLock.current=true;setInterrupting(true);setControlNotice('正在取回排队消息…');setError('');
  try{const count=await takePiQueuedMessages(controlCommand,restoreQueuedDraft);setControlNotice(`已取回 ${count} 条排队消息并放回输入框，不会自动发送。当前回复和后台任务不受影响。`)}
  catch(cause){setControlNotice('');setError(cause instanceof Error?cause.message:'排队消息取回结果待核实。')}
  finally{interruptLock.current=false;setInterrupting(false)}
 }
 async function interruptReply(clearQueue=false){
  if(!status.canInterrupt||interruptLock.current)return;
  interruptLock.current=true;setInterrupting(true);setControlNotice(clearQueue?'正在清空排队消息并请求中断…':'正在请求中断当前回复…');setError('');
  try{await interruptPiReply(clearQueue,controlCommand,restoreQueuedDraft);setControlNotice(clearQueue?'Pi 已确认中断；已取回的排队消息放回输入框，不会自动发送。后台任务和财务任务请在各自页面查看。':'Pi 已确认中断当前回复；排队消息未清空。后台任务和财务任务请在各自页面查看。')}
  catch(cause){setControlNotice('');setError(cause instanceof Error?cause.message:'中断结果待核实。')}
  finally{interruptLock.current=false;setInterrupting(false)}
 }
 const acknowledgeDelivery=()=>{activeDeliveryRequest.current=null;try{removePiStorage('delivery',storageScope,sessionId);removePiStorage('attachment-send',storageScope,sessionId)}catch{}setDelivery(null);setError('请确认历史中没有重复请求，再作为新消息发送。')};
 const closeEnvironment=()=>op('stop').then(()=>{dialogObservation.current=false;setRunning(false);setWorking(false);setSending(false)}).catch(e=>setError(e.message));
 const changeModel=(value:string)=>{const [provider,modelId]=JSON.parse(value);void action('set_model',{provider,modelId})};
 return {
  view:{interrupting,controlNotice,artifacts:artifacts.view,status,connectionError,commands,commandsOpen,messages,input,error,running,working,sending,queueMode,models,model,thinking,pending,dialogs,delivery,uncertainDelivery,uploading,uploadProgress,attachments},
  actions:{refreshArtifacts:artifacts.refresh,setCommandsOpen,setInput,setError,setQueueMode,setAttachments,queryDelivery,connect,upload,submit,acknowledgeDelivery,closeEnvironment,changeModel,
   interruptReply,takeQueuedMessages,compactContext:()=>action('compact'),refreshCommands:()=>action('get_commands'),
   changeThinking:(level:string)=>action('set_thinking_level',{level}),
   replyToDialog:async(command:Record<string,unknown>)=>{if(!permitsPiDialogResponse(capabilitiesRef.current,command))throw new Error('Skill 权限已变化，目前只能拒绝或取消此请求。');const checked=validatePiDialogReply(dialogObservation.current&&status.canReplyToDialog,dialogs,command);return op('send',{command:checked})}}
 };
}
