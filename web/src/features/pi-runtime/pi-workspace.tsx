'use client';

import { useEffect, useRef, useState } from 'react';
import type { Terminal } from '@xterm/xterm';
import { PiFiles } from './pi-files';
import {PiSkillProposals} from './pi-skill-proposals';
import '@xterm/xterm/css/xterm.css';

export type PiSession = { id: string; title: string; created_at: string; skill_id?: string; skill_commit?: string; channel?: 'assistant'|'workspace' };
type PiEvent = { sequence: number; kind: string; data?: string; text?: string };
type PiPoll = { running: boolean; mode?: string; events: PiEvent[]; next: number; gap?: boolean; instance_id?: string };

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/platform/pi-runtime${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store'
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : typeof value.message === 'string' ? value.message : 'Pi 请求失败，请重试。');
  return value as T;
}

function operate<T>(id: string, operation: string, payload: unknown = {}) {
  return request<T>(`/sessions/${encodeURIComponent(id)}/operate`, { operation, payload });
}

function encodeInput(bytes: Uint8Array): string {
  return btoa(Array.from(bytes, (value) => String.fromCharCode(value)).join(''));
}

function PiTerminal({ sessionId }: { sessionId: string }) {
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const stopping = useRef(false);
  const [running, setRunning] = useState(false);
  const [mode, setMode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let disposed = false;
    let cursor = 0;
    let instance = '';
    let isRunning = false;
    let currentMode = '';
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inputTimer: ReturnType<typeof setTimeout> | undefined;
    let input = '';
    let observer: ResizeObserver | undefined;
    let term: Terminal | undefined;
    let queue = Promise.resolve();
    const enqueue = (operation: string, payload: unknown) => {
      queue = queue.then(async () => {
        if (!disposed && !stopping.current) await operate(sessionId, operation, payload);
      }).catch((cause: unknown) => { if (!disposed && !stopping.current) setError(cause instanceof Error ? cause.message : '终端连接失败'); });
    };
    const setup = async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]);
      if (disposed || !host.current) return;
      term = new Terminal({ cursorBlink: true, fontSize: 14, fontFamily: 'Consolas, "Noto Sans Mono", monospace', scrollback: 8000, theme: { background: '#171717', foreground: '#e8e5df' }, allowProposedApi: false });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(host.current);
      terminal.current = term;
      const resize = () => {
        if (disposed || !term) return;
        fit.fit();
        if (isRunning && currentMode === 'terminal') enqueue('resize', { rows: term.rows, cols: term.cols });
      };
      resize();
      observer = new ResizeObserver(resize);
      observer.observe(host.current);
      term.onData((data) => {
        if (!isRunning || currentMode !== 'terminal') return;
        input += data;
        if (!inputTimer) inputTimer = setTimeout(() => {
          const pending = input; input = ''; inputTimer = undefined;
          // Split encoded bytes without corrupting Unicode surrogate pairs.
          const bytes = new TextEncoder().encode(pending);
          for (let offset = 0; offset < bytes.length; offset += 16000) enqueue('send', { data: encodeInput(bytes.subarray(offset, offset + 16000)) });
        }, 20);
      });
      const poll = async () => {
        try {
          const value = await operate<PiPoll>(sessionId, 'poll', { after: cursor });
          if (disposed || !term) return;
          if (instance && value.instance_id && instance !== value.instance_id) {
            cursor = 0; term.reset(); instance = value.instance_id;
          } else {
            instance = value.instance_id ?? instance;
            if (value.gap) {
              term.reset();
              term.writeln('终端历史输出已截断，正在重绘当前画面。');
            }
            for (const event of value.events ?? []) {
              if (event.kind === 'terminal' && event.data) term.write(Uint8Array.from(atob(event.data), (char) => char.charCodeAt(0)));
              else if (event.kind === 'stderr' && event.text) term.write(event.text);
            }
            cursor = value.next ?? cursor;
            const wasRunning = isRunning;
            isRunning = value.running;
            currentMode = value.mode ?? '';
            setRunning(isRunning); setMode(currentMode);
            if (isRunning && currentMode === 'terminal' && (!wasRunning || value.gap)) {
              enqueue('resize', { rows: term.rows, cols: term.cols + 1 });
              enqueue('resize', { rows: term.rows, cols: term.cols });
            }
          }
        } catch (cause) {
          if (!disposed) setError(cause instanceof Error ? cause.message : '终端连接中断，将继续尝试连接。');
        } finally {
          if (!disposed) timer = setTimeout(poll, isRunning ? 250 : 1500);
        }
      };
      await poll();
    };
    setup().catch((cause: unknown) => { if (!disposed) setError(cause instanceof Error ? cause.message : '无法初始化终端'); });
    return () => {
      disposed = true; clearTimeout(timer); clearTimeout(inputTimer);
      observer?.disconnect(); term?.dispose(); terminal.current = null;
      // Leaving the page intentionally does not stop the remote Pi process.
    };
  }, [sessionId]);

  async function start() {
    stopping.current = false;
    setBusy(true); setError('');
    try { await operate(sessionId, 'start', { mode: 'terminal' }); terminal.current?.focus(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '启动失败'); }
    finally { setBusy(false); }
  }
  async function stop() {
    stopping.current = true;
    setBusy(true); setError('');
    try { await operate(sessionId, 'stop'); setRunning(false); }
    catch (cause) { stopping.current = false; setError(cause instanceof Error ? cause.message : '停止失败'); }
    finally { setBusy(false); }
  }

  return <div className='flex min-h-0 flex-1 flex-col gap-3'>
    <div className='flex flex-wrap items-center justify-between gap-3'>
      <span className='text-muted-foreground text-sm' aria-live='polite'>{running ? mode === 'terminal' ? '运行中 · 刷新或离开页面不会停止任务' : '当前会话正在对话模式运行' : '已停止 · 工作文件与会话历史仍保留'}</span>
      <div className='flex gap-2'>
        <button className='bg-primary text-primary-foreground rounded-md px-3 py-2 text-sm disabled:opacity-50' onClick={start} disabled={busy || running}>启动 Pi</button>
        <button className='border-input rounded-md border px-3 py-2 text-sm disabled:opacity-50' onClick={stop} disabled={busy}>停止运行</button>
      </div>
    </div>
    {error && <div role='alert' className='text-destructive flex items-center justify-between gap-2 rounded-md border p-3 text-sm'>{error}<button onClick={() => setError('')} aria-label='关闭错误提示'>×</button></div>}
    <div ref={host} className='h-[65vh] min-h-[360px] max-h-[900px] flex-none overflow-hidden rounded-xl border bg-[#171717] p-3' aria-label='Pi 交互终端' />
    <p className='text-muted-foreground text-xs'>默认接入平台可用模型；使用 /model 切换模型、/login 配置个人账号、/hotkeys 查看快捷键。工作文件保存在 /workspace；用户配置和安装的依赖随账号保留。</p>
  </div>;
}

export function PiWorkspace({ initialSessions, initialSessionId, skillId }: { initialSessions: PiSession[]; initialSessionId?: string; skillId?: string }) {
  const [sessions, setSessions] = useState(initialSessions);
  const [selected, setSelected] = useState(initialSessions.some((item) => item.id === initialSessionId) ? initialSessionId! : initialSessions[0]?.id ?? '');
  const [title, setTitle] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const url = new URL(window.location.href);
    if (selected) url.searchParams.set('session', selected); else url.searchParams.delete('session');
    window.history.replaceState(null, '', url.toString());
  }, [selected]);
  async function create() {
    setCreating(true); setError('');
    try {
      const item = await request<PiSession>('/sessions', { channel: 'workspace', title: title.trim() || (skillId ? `${skillId} 对话` : 'Pi 会话'), ...(skillId ? {skill_id:skillId} : {}) });
      setSessions((items) => [item, ...items]); setSelected(item.id); setTitle('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : '创建会话失败'); }
    finally { setCreating(false); }
  }
  return <div className='flex min-h-[650px] flex-col gap-4'>
    <div className='flex flex-wrap items-center gap-3'>
      <select aria-label='选择 Pi 会话' value={selected} onChange={(event) => setSelected(event.target.value)} className='border-input bg-background max-w-full min-w-48 rounded-md border px-3 py-2 text-sm'>
        {!sessions.length && <option value=''>尚无会话</option>}
        {sessions.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.id.slice(0, 8)}</option>)}
      </select>
      <input aria-label='新会话名称' placeholder='新会话名称' value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} className='border-input bg-background min-w-40 rounded-md border px-3 py-2 text-sm' onKeyDown={(event) => { if (event.key === 'Enter' && !creating) void create(); }} />
      <button onClick={create} disabled={creating} className='border-input rounded-md border px-3 py-2 text-sm disabled:opacity-50'>{creating ? '创建中…' : '新建会话'}</button>
    </div>
    {skillId && <p className='text-muted-foreground text-xs'>使用完整 Pi 运行环境；Skill 版本固定到当前会话，更新 Skill 后新建会话即可使用新版。</p>}
    {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
    <details><summary className='cursor-pointer text-sm'>Skill 发布确认</summary><PiSkillProposals/></details>
    {selected && <PiFiles key={'files-'+selected} sessionId={selected} />}
    {selected ? <PiTerminal key={selected} sessionId={selected} /> : <div className='text-muted-foreground flex min-h-[440px] items-center justify-center rounded-xl border text-sm'>创建一个会话，开始使用 Pi。</div>}
  </div>;
}
