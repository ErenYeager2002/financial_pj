'use client';
import {useState} from 'react';
import {IconCheck,IconChevronRight,IconCopy,IconFileText} from '@tabler/icons-react';
import {AssistantResponse} from '@/features/ai-chat/assistant-response';
import {PiMessageImages,type PiImageBlock} from './pi-message-images';
import {resolveAgentFile} from './pi-file-transfer';
import styles from './pi-chat-design.module.css';
export type ChatBlock=PiImageBlock & {text?:string;thinking?:string;name?:string;id?:string;arguments?:unknown};
export type ChatMessage={role:string;content?:string|ChatBlock[];timestamp?:number;toolCallId?:string;toolName?:string;isError?:boolean;stopReason?:string;errorMessage?:string};
export function messageText(message:ChatMessage){return typeof message.content==='string'?message.content:(message.content??[]).filter(item=>item.type==='text').map(item=>item.text??'').join('')}
export function messageKey(message:ChatMessage){return message.toolCallId??`${message.role}:${message.timestamp??0}`}
function UserMessage({text,sessionId}:{text:string;sessionId:string}){
 const separator='\n\n附件（已上传）：\n';const at=text.lastIndexOf(separator);const files:{name:string;url:string}[]=[];
 if(at>=0){for(const line of text.slice(at+separator.length).split('\n')){const match=/^- (".*")：(".*")$/.exec(line);try{if(!match)throw Error();const name=JSON.parse(match[1]),path=JSON.parse(match[2]);const url=typeof path==='string'?resolveAgentFile(sessionId,path):undefined;if(typeof name!=='string'||!url)throw Error();files.push({name,url})}catch{return <p className='whitespace-pre-wrap break-words'>{text}</p>}}}
 return <><p className='whitespace-pre-wrap break-words'>{at>=0?text.slice(0,at):text}</p>{files.length>0&&<div className='mt-2 flex flex-wrap gap-2'>{files.map((file,index)=><a key={file.url+index} href={file.url} download className={styles.attachment}><IconFileText size={15}/><span>{file.name}</span></a>)}</div>}</>;
}
function CopyResponse({text}:{text:string}){
 const [copied,setCopied]=useState(false);const [error,setError]=useState(false);
 async function copy(){try{if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(text);else{const area=document.createElement('textarea');area.value=text;area.style.cssText='position:fixed;opacity:0;pointer-events:none';document.body.appendChild(area);const focus=document.activeElement;try{area.select();if(!document.execCommand('copy'))throw Error('copy')}finally{area.remove();if(focus instanceof HTMLElement)focus.focus()}}setCopied(true);setError(false)}catch{setError(true)}}
 return <div className={styles.responseActions}><button className={styles.iconButton} aria-label={copied?'已复制回答':'复制回答'} title={copied?'已复制':'复制回答'} onClick={()=>void copy()}>{copied?<IconCheck size={15}/>:<IconCopy size={15}/>}</button>{error&&<span role='status' className='text-xs'>复制失败，请选择文字复制</span>}</div>;
}
const toolNames:Record<string,string>={bash:'执行命令',read:'读取文件',write:'写入文件',edit:'修改文件',grep:'搜索内容',find:'查找文件',ls:'查看目录',shared_memory:'会话记忆'};
export function PiChatMessages({messages,sessionId}:{messages:ChatMessage[];sessionId:string}){
 const completed=new Set(messages.filter(m=>m.role==='toolResult').map(m=>m.toolCallId));
 return <>{messages.map((message,index)=>{const text=messageText(message);const blocks=Array.isArray(message.content)?message.content:[];
 if(message.role==='toolResult')return <details key={messageKey(message)+index} className={styles.tool}><summary><IconChevronRight size={13}/>{message.isError?'执行出错':'已完成'} · {toolNames[message.toolName??'']??message.toolName??'工具'}</summary><pre>{text}</pre><PiMessageImages blocks={blocks}/></details>;
 if(message.role!=='user'&&message.role!=='assistant')return null;
 const calls=blocks.filter(block=>block.type==='toolCall'&&!completed.has(block.id));
 if(!text&&!message.errorMessage&&message.stopReason!=='aborted'&&calls.length===0&&!blocks.some(block=>block.type==='image'))return null;
 return <div key={messageKey(message)+index} className={message.role==='user'?styles.userRow:undefined}><article className={message.role==='user'?styles.user:styles.assistant} aria-label={message.role==='user'?'我的消息':'助手回答'}>
 {message.errorMessage&&<p role='alert' className='text-destructive whitespace-pre-wrap'>{message.errorMessage}</p>}
 {message.stopReason==='aborted'&&<p className='text-muted-foreground text-xs'>本次回复已中断</p>}
 {text&&(message.role==='user'?<UserMessage text={text} sessionId={sessionId}/>:<AssistantResponse content={text} resolveFileLink={href=>resolveAgentFile(sessionId,href)}/>)}
 <PiMessageImages blocks={blocks}/>
 {calls.map((call,i)=><details className={styles.tool} key={call.id??i}><summary><IconChevronRight size={13}/>{toolNames[call.name??'']??call.name??'工具调用'}</summary><pre>{JSON.stringify(call.arguments,null,2)}</pre></details>)}
 {message.role==='assistant'&&text&&<CopyResponse text={text}/>}
 </article></div>;
 })}</>;
}
