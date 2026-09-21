'use client';
import {useRef, useState} from 'react';
import Link from 'next/link';
import type {PiSession} from './pi-workspace';
import styles from './pi-chat-design.module.css';

type State = {environment_running?: boolean; running: boolean; mode?: string; activity?: {busy: boolean; phase: string} | null};
type Row = PiSession & {state?: State; error?: string};
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api/platform/pi-runtime' + path, {
    method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
    headers: body === undefined ? undefined : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : typeof value.message === 'string' ? value.message : '读取运行环境失败');
  return value;
}
function operation<T>(id: string, operation: string) {
  return request<T>(`/sessions/${encodeURIComponent(id)}/operate`, {operation, payload: operation === 'poll' ? {after: Number.MAX_SAFE_INTEGER} : {}});
}
function href(row: Row) {
  return (row.skill_id ? `/dashboard/installed-skills/${encodeURIComponent(row.skill_id)}/run` : '/dashboard/ai-chat') + '?session=' + encodeURIComponent(row.id);
}
export function SessionEnvironments({currentSessionId}: {currentSessionId: string}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [closing, setClosing] = useState('');
  const [confirm, setConfirm] = useState('');
  const [notice, setNotice] = useState('');
  async function refresh() {
    setLoading(true); setError('');
    try {
      const sessions = await request<PiSession[]>('/sessions');
      const next: Row[] = [];
      // Bound concurrent polls; opening this panel never starts an environment.
      for (let i = 0; i < sessions.length; i += 3) {
        const batch = await Promise.all(sessions.slice(i, i + 3).map(async (row): Promise<Row> => {
          try {return {...row, state: await operation<State>(row.id, 'poll')};}
          catch (cause) {return {...row, error: cause instanceof Error ? cause.message : '状态读取失败'};}
        }));
        next.push(...batch);
      }
      setRows(next);
    } catch (cause) {setError(cause instanceof Error ? cause.message : '读取失败');}
    finally {setLoading(false);}
  }
  async function stop(row: Row) {
    setClosing(row.id); setError(''); setNotice('');
    try {
      await operation(row.id, 'stop');
      setConfirm(''); setNotice('环境已关闭，聊天记录和文件已保留。再次发送消息时会恢复环境。');
      await refresh();
    } catch (cause) {setError(cause instanceof Error ? cause.message : '关闭失败');}
    finally {setClosing('');}
  }
  const active = rows.filter(row => !row.error && row.state?.environment_running !== false).length;
  return <>
    <button type='button' className={styles.chip} onClick={() => {dialog.current?.showModal(); setConfirm(''); setNotice(''); void refresh();}}>运行环境</button>
    <dialog ref={dialog} aria-label='运行环境' className='bg-background text-foreground fixed inset-0 m-auto max-h-[80dvh] w-[min(44rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border p-5 shadow-xl backdrop:bg-black/40'>
      <div className='flex items-center justify-between gap-3'><h2 className='text-base font-semibold'>运行环境</h2><button type='button' className={styles.chip} onClick={() => dialog.current?.close()}>关闭面板</button></div>
      <p className='text-muted-foreground my-3 text-sm'>显示你所有对话的环境，包括 AI 助手、Skill 对话及旧工作区。关闭环境会中断其中的回复和任务，保留聊天记录与文件。</p>
      <div className='mb-3 flex items-center justify-between gap-3'><span className='text-sm'>{loading ? '正在读取状态…' : `${active} 个环境占用名额${rows.some(row => row.error) ? '，另有状态读取失败的会话' : ''}`}</span><button type='button' className={styles.chip} disabled={loading || Boolean(closing)} onClick={() => void refresh()}>刷新状态</button></div>
      {error && <p role='alert' className='text-destructive mb-3 text-sm'>{error}</p>}
      {notice && <p role='status' className='mb-3 text-sm'>{notice}</p>}
      <div className='space-y-3'>{rows.map(row => {
        const stopped = row.state?.environment_running === false;
        const busy = row.state?.activity?.busy;
        return <div key={row.id} className='rounded-lg border p-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'><Link href={href(row)} onClick={() => dialog.current?.close()} className='font-medium underline underline-offset-4'>{row.title}{row.id === currentSessionId ? '（当前会话）' : ''}</Link><span className='text-muted-foreground text-xs'>{row.error ? '状态未知' : stopped ? '已关闭，不占名额' : busy ? '正在执行' : row.state?.mode === 'terminal' ? '旧终端，执行状态待核实' : row.state?.activity ? '等待消息' : '环境已启动'}</span></div>
          <p className='text-muted-foreground mt-1 break-all text-xs'>{row.skill_id || (row.channel === 'workspace' ? '旧工作区' : 'AI 助手')} · {row.id}</p>
          {row.error && <p className='text-destructive mt-2 text-xs'>{row.error}</p>}
          {!stopped && <div className='mt-2'>
            {confirm === row.id ? <div className='space-y-2'><p className='text-sm'>确认关闭此会话的环境？未完成的回复和后台任务会停止；这不会删除聊天记录或文件。</p><div className='flex gap-2'><button type='button' className={styles.chip} disabled={Boolean(closing) || loading} onClick={() => void stop(row)}>{closing === row.id ? '正在关闭…' : '确认关闭环境'}</button><button type='button' className={styles.chip} disabled={Boolean(closing)} onClick={() => setConfirm('')}>取消</button></div></div> : <button type='button' className={styles.chip} disabled={Boolean(closing) || loading} onClick={() => setConfirm(row.id)}>关闭环境</button>}
          </div>}
        </div>;
      })}</div>
      {!loading && !rows.length && !error && <p className='text-muted-foreground text-sm'>尚无会话环境。</p>}
    </dialog>
  </>;
}
