'use client';
/* Adapted from bytedance/deer-flow @ d3a9c123 (MIT, see ./NOTICE):
   frontend/src/components/workspace/messages/tool-call-details.tsx
   Upstream LangGraph ToolCall/Message types replaced with platform-owned
   display props; i18n/clipboard helpers replaced with platform equivalents. */
import {useEffect, useId, useMemo, useState} from 'react';
import {IconCheck, IconChevronRight, IconCopy, IconTerminal2} from '@tabler/icons-react';
import styles from './deerflow-chat.module.css';

const toolNames: Record<string, string> = {bash: '执行命令', read: '读取文件', write: '写入文件', edit: '修改文件', grep: '搜索内容', find: '查找文件', ls: '查看目录', shared_memory: '会话记忆'};

export function deerflowToolLabel(name?: string) {
  return toolNames[name ?? ''] ?? name ?? '工具调用';
}

function previewText(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2) ?? '';
  } catch {
    return String(value);
  }
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
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

function Payload({label, value}: {label: string; value: unknown}) {
  const text = useMemo(() => previewText(value), [value]);
  const [status, setStatus] = useState<'copied' | 'failed' | ''>('');
  useEffect(() => {
    if (!status) return;
    const timer = setTimeout(() => setStatus(''), 2000);
    return () => clearTimeout(timer);
  }, [status]);
  return (
    <section aria-label={label} className={styles.payload}>
      <div className={styles.payloadHeader}>
        <span>{label}</span>
        <button type='button' className={styles.payloadCopy} aria-label={`复制${label}`}
          onClick={() => void copyText(text).then(() => setStatus('copied'), () => setStatus('failed'))}>
          {status === 'copied' ? <IconCheck size={13}/> : <IconCopy size={13}/>}
          {status === 'copied' ? '已复制' : status === 'failed' ? '复制失败' : '复制'}
        </button>
      </div>
      <pre className={styles.payloadPre}>{text === '' ? '""' : text}</pre>
      {text === '' && <p className='text-muted-foreground text-xs'>空内容</p>}
    </section>
  );
}

export function DeerflowToolCall({name, callId, args, result, isError}: {
  name?: string;
  callId?: string;
  args?: unknown;
  result?: string;
  isError?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const done = result !== undefined;
  return (
    <div className={styles.toolCard}>
      <button type='button' className={styles.toolSummary} aria-expanded={open} aria-controls={panelId}
        aria-label={`工具调用详情：${deerflowToolLabel(name)}${callId ? ` (${callId})` : ''}`}
        onClick={() => setOpen(value => !value)}>
        <IconChevronRight size={13} className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}/>
        <IconTerminal2 size={14}/>
        <span>{deerflowToolLabel(name)}</span>
        <span className={`${styles.toolStatus} ${isError ? styles.toolStatusError : ''}`}>
          {isError ? '执行出错' : done ? '已完成' : '执行中'}
        </span>
      </button>
      {open && (
        <div id={panelId} className={styles.toolPanel}>
          <Payload label='工具' value={deerflowToolLabel(name)}/>
          {callId && <Payload label='调用 ID' value={callId}/>}
          {args !== undefined && <Payload label='输入' value={args}/>}
          {done ? <Payload label={isError ? '错误' : '结果'} value={result}/> : <p className='text-muted-foreground text-xs'>尚无结果</p>}
        </div>
      )}
    </div>
  );
}
