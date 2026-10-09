'use client';
/* Adapted from bytedance/deer-flow @ d3a9c123 (MIT, see ./NOTICE):
   frontend/src/components/ai-elements/message.tsx (shell/layout only).
   Message protocol, visibility rules, safe Markdown and file resolution are
   the platform's own (../pi-chat-messages.tsx, AssistantResponse). Renders the
   exact same ChatMessage stream as the legacy renderer with identical
   visibility semantics — only presentation differs. */
import {useState, type ReactNode} from 'react';
import {IconCheck, IconCopy, IconFileText} from '@tabler/icons-react';
import {AssistantResponse} from '@/features/ai-chat/assistant-response';
import {PiMessageImages} from '../pi-message-images';
import {resolveAgentFile} from '../pi-file-transfer';
import {isVisiblePiCustomMessage} from '../pi-message-visibility';
import {messageText, messageKey, type ChatMessage, type ChatBlock} from '../pi-chat-messages';
import {DeerflowConversation} from './deerflow-conversation';
import {DeerflowToolCall, deerflowToolLabel} from './deerflow-tool-call';
import styles from './deerflow-chat.module.css';

function DfMessage({from, label, children}: {from: 'user' | 'assistant'; label: string; children: ReactNode}) {
  return (
    <div className={`${styles.message} ${from === 'user' ? styles.messageUser : styles.messageAssistant}`}>
      <article aria-label={label} className={styles.content}>{children}</article>
    </div>
  );
}

function UserText({text, sessionId}: {text: string; sessionId: string}) {
  const separator = '\n\n附件（已上传）：\n';
  const at = text.lastIndexOf(separator);
  const files: {name: string; url: string}[] = [];
  if (at >= 0) {
    for (const line of text.slice(at + separator.length).split('\n')) {
      const match = /^- (".*")：(".*")$/.exec(line);
      try {
        if (!match) throw Error();
        const name = JSON.parse(match[1]), path = JSON.parse(match[2]);
        const url = typeof path === 'string' ? resolveAgentFile(sessionId, path) : undefined;
        if (typeof name !== 'string' || !url) throw Error();
        files.push({name, url});
      } catch {
        return <p className='whitespace-pre-wrap break-words'>{text}</p>;
      }
    }
  }
  return (
    <>
      <p className='whitespace-pre-wrap break-words'>{at >= 0 ? text.slice(0, at) : text}</p>
      {files.length > 0 && (
        <div className={styles.attachments}>
          {files.map((file, index) => (
            <a key={file.url + index} href={file.url} download className={styles.attachmentChip}>
              <IconFileText size={15}/><span>{file.name}</span>
            </a>
          ))}
        </div>
      )}
    </>
  );
}

function CopyAction({text}: {text: string}) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  async function copy() {
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
        document.body.appendChild(area);
        const focus = document.activeElement;
        try {
          area.select();
          if (!document.execCommand('copy')) throw Error('copy');
        } finally {
          area.remove();
          if (focus instanceof HTMLElement) focus.focus();
        }
      }
      setCopied(true);
      setError(false);
    } catch {
      setError(true);
    }
  }
  return (
    <div className={styles.actions}>
      <button className={styles.iconButton} aria-label={copied ? '已复制回答' : '复制回答'} title={copied ? '已复制' : '复制回答'} onClick={() => void copy()}>
        {copied ? <IconCheck size={15}/> : <IconCopy size={15}/>}
      </button>
      {error && <span role='status' className='text-xs'>复制失败，请选择文字复制</span>}
    </div>
  );
}

function hasImage(blocks: ChatBlock[]) {
  return blocks.some(block => block.type === 'image');
}

export function DeerflowMessages({messages, sessionId}: {messages: ChatMessage[]; sessionId: string}) {
  const completed = new Set(messages.filter(m => m.role === 'toolResult').map(m => m.toolCallId));
  return (
    <DeerflowConversation>
      {messages.map((message, index) => {
        const text = messageText(message);
        const blocks = Array.isArray(message.content) ? message.content : [];
        const key = messageKey(message) + index;
        if (message.role === 'toolResult') {
          return (
            <DfMessage key={key} from='assistant' label='工具结果'>
              <DeerflowToolCall name={message.toolName} callId={message.toolCallId} result={text} isError={message.isError}/>
              <PiMessageImages blocks={blocks}/>
            </DfMessage>
          );
        }
        if (isVisiblePiCustomMessage(message)) {
          return (
            <DfMessage key={key} from='assistant' label='扩展消息'>
              <p className={styles.caption}>{message.customType || '扩展消息'}</p>
              {text && <div className={styles.markdown}><AssistantResponse content={text} resolveFileLink={href => resolveAgentFile(sessionId, href)}/></div>}
              <PiMessageImages blocks={blocks}/>
            </DfMessage>
          );
        }
        if (message.role !== 'user' && message.role !== 'assistant') return null;
        const calls = blocks.filter(block => block.type === 'toolCall' && !completed.has(block.id));
        if (!text && !message.errorMessage && message.stopReason !== 'aborted' && calls.length === 0 && !hasImage(blocks)) return null;
        const role = message.role === 'user' ? 'user' : 'assistant';
        return (
          <DfMessage key={key} from={role} label={role === 'user' ? '我的消息' : '助手回答'}>
            {message.errorMessage && <p role='alert' className='text-destructive whitespace-pre-wrap'>{message.errorMessage}</p>}
            {message.stopReason === 'aborted' && <p className={styles.caption}>本次回复已中断</p>}
            {text && (role === 'user'
              ? <UserText text={text} sessionId={sessionId}/>
              : <div className={styles.markdown}><AssistantResponse content={text} resolveFileLink={href => resolveAgentFile(sessionId, href)}/></div>)}
            <PiMessageImages blocks={blocks}/>
            {calls.map((call, i) => (
              <DeerflowToolCall key={call.id ?? i} name={call.name} callId={call.id} args={call.arguments}/>
            ))}
            {role === 'assistant' && text && <CopyAction text={text}/>}
          </DfMessage>
        );
      })}
    </DeerflowConversation>
  );
}

export {deerflowToolLabel};
