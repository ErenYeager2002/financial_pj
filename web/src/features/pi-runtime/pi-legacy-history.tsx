'use client';
import {useEffect,useState} from 'react';
import type {AssistantConversation,AssistantConversationSummary} from '@/features/platform-api/types';
import {belongsToSkillSession} from '@/features/ai-chat/skill-chat-scope';
export function PiLegacyHistory({skillId}:{skillId?:string}) {
 const [open,setOpen]=useState(false);const [items,setItems]=useState<AssistantConversationSummary[]>([]);
 const [selected,setSelected]=useState('');const [conversation,setConversation]=useState<AssistantConversation|null>(null);const [error,setError]=useState('');
 useEffect(()=>{if(!open)return;const controller=new AbortController();
  fetch('/api/platform/assistant/conversations',{cache:'no-store',signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error('旧对话列表读取失败');return response.json()}).then((value:AssistantConversationSummary[])=>{if(!controller.signal.aborted)setItems(value.filter(item=>belongsToSkillSession(item.session_id,skillId?`native--${skillId}`:undefined)))}).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
  return()=>controller.abort();
 },[open,skillId]);
 useEffect(()=>{setConversation(null);setError('');if(!selected)return;const controller=new AbortController();
  fetch(`/api/platform/assistant/conversations/${encodeURIComponent(selected)}`,{cache:'no-store',signal:controller.signal}).then(async response=>{if(!response.ok)throw new Error('旧对话读取失败');return response.json()}).then((value:AssistantConversation)=>{if(!controller.signal.aborted)setConversation(value)}).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
  return()=>controller.abort();
 },[selected]);
 return <details className='mb-2 rounded-lg border px-3 py-2' onToggle={e=>setOpen(e.currentTarget.open)}>
  <summary className='cursor-pointer text-sm'>查看升级前的对话记录</summary>
  <p className='text-muted-foreground my-2 text-xs'>旧对话记录保留在这里。使用完整 Pi 能力请在下方新建会话；查看历史不会重新执行任务。</p>
  <select aria-label='升级前的对话' value={selected} onChange={e=>setSelected(e.target.value)} className='bg-background max-w-full rounded border p-2 text-sm'><option value=''>选择历史对话</option>{items.map(item=><option key={item.session_id} value={item.session_id}>{item.preview||item.session_id} · {item.message_count} 条</option>)}</select>
  {error&&<p role='alert'>{error}</p>}
  <div className='mt-3 max-h-96 space-y-3 overflow-auto'>{conversation?.session_id===selected&&conversation.messages?.map(message=><article key={message.id} className='rounded border p-3'><p className='text-muted-foreground text-xs'>{message.role==='user'?'你':message.role==='assistant'?'AI':'系统'} · {message.created_at}</p><p className='mt-1 whitespace-pre-wrap break-words text-sm'>{message.content}</p></article>)}</div>
 </details>;
}
