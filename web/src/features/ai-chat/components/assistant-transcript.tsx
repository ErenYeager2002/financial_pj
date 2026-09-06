'use client';

import { useEffect, useRef } from 'react';
import { Icons } from '@/components/icons';
import { AssistantResponse } from '@/features/ai-chat/assistant-response';
import { formatDate } from '@/lib/format';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt?: string;
}

interface AssistantTranscriptProps {
  messages: ChatMessage[];
  historical?: boolean;
  checkedAt?: string;
}

export function AssistantTranscript({ messages, historical = false, checkedAt }: AssistantTranscriptProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const followEndRef = useRef(true);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport && followEndRef.current) viewport.scrollTop = viewport.scrollHeight;
  }, [messages]);

  function updateFollowState() {
    const viewport = viewportRef.current;
    if (!viewport) return;
    followEndRef.current =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 96;
  }

  return (
    <div
      ref={viewportRef}
      role='region'
      aria-label='对话消息'
      className='min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain px-4 py-6'
      onScroll={updateFollowState}
    >
      {historical && (
        <p className='mb-5 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground'>
          这是历史会话查询结果；任务状态以消息记录为准。查询时间：
          {checkedAt
            ? `${formatDate(checkedAt, {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
              })}（北京时间）`
            : '待核实'}
        </p>
      )}
      <div className='mx-auto w-full max-w-[840px] space-y-6'>
        {messages.map((message) => (
          <div
            key={message.id}
            className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
          >
            <div
              className={
                message.role === 'user'
                  ? 'min-w-0 max-w-[90%] sm:max-w-[82%] break-words whitespace-pre-wrap rounded-lg bg-muted px-3 py-2 text-sm leading-6'
                  : 'min-w-0 max-w-full break-words text-[15px] leading-6'
              }
            >
              {message.content ? (
                message.role === 'assistant' ? (
                  <AssistantResponse content={message.content} />
                ) : (
                  message.content
                )
              ) : (
                <Icons.spinner className='size-4 animate-spin' aria-label='正在生成回复' />
              )}
              {message.createdAt && (
                <p className='mt-1 text-xs text-muted-foreground'>
                  {formatDate(message.createdAt, {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                  })}{' '}
                  （北京时间）
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export type { ChatMessage };
