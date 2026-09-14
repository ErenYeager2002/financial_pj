'use client';
import { BrandIcon } from '@/components/brand-icon';
import React from 'react';

type MaintenanceState = { mode: 'normal' | 'notice' | 'worker' | 'full'; message: string };
const NORMAL: MaintenanceState = { mode: 'normal', message: '' };

export function MaintenanceNotice() {
  const [state, setState] = React.useState<MaintenanceState>(NORMAL);
  React.useEffect(() => {
    const originalFetch = window.fetch;
    const nativeFetch = originalFetch.bind(window);
    let mode: MaintenanceState['mode'] = 'normal';
    let disposed = false;
    let checking = false;
    async function check() {
      if (checking || disposed) return;
      checking = true;
      try {
        const response = await nativeFetch('/maintenance/status', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
        if (!response.ok) return;
        const value = await response.json() as MaintenanceState;
        if (disposed || !['normal', 'notice', 'worker', 'full'].includes(value.mode)) return;
        mode = value.mode;
        setState({ mode, message: typeof value.message === 'string' ? value.message : '' });
      } catch {
        // Keep the last known state; a lost connection never replays an operation.
      } finally { checking = false; }
    }
    const wrappedFetch: typeof window.fetch = async (input, init) => {
      const request = input instanceof Request ? input : null;
      const url = new URL(request?.url ?? String(input), location.href);
      const method = (init?.method ?? request?.method ?? 'GET').toUpperCase();
      const internal = url.origin === location.origin && !url.pathname.startsWith('/maintenance/');
      const mutation = !['GET', 'HEAD', 'OPTIONS'].includes(method) && !['/api/auth/login', '/api/auth/logout'].includes(url.pathname);
      if (internal && (mode === 'full' || (mode !== 'normal' && mutation))) {
        return new Response(JSON.stringify({ detail: '平台正在维护，暂时无法提交操作。请稍候再试。', maintenance: true }), { status: 503, headers: { 'Content-Type': 'application/json', 'Retry-After': '10' } });
      }
      const response = await nativeFetch(input, init);
      if (internal && response.status === 503) void check();
      return response;
    };
    window.fetch = wrappedFetch;
    void check();
    const timer = window.setInterval(() => void check(), 5000);
    const resume = () => { if (document.visibilityState === 'visible') void check(); };
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('focus', resume);
    window.addEventListener('online', resume);
    return () => { disposed = true; window.clearInterval(timer); document.removeEventListener('visibilitychange', resume); window.removeEventListener('focus', resume); window.removeEventListener('online', resume); if (window.fetch === wrappedFetch) window.fetch = originalFetch; };
  }, []);

  if (state.mode === 'normal') return null;
  if (state.mode === 'full') return (
    <div role='dialog' aria-modal='true' aria-labelledby='maintenance-title' className='fixed inset-0 z-[1000] overflow-y-auto bg-background text-foreground' onKeyDown={(event) => { if (event.key === 'Tab') event.preventDefault(); }} ref={(element) => { if (element && !element.contains(document.activeElement)) element.focus(); }} tabIndex={-1}>
      <header className='flex h-[68px] items-center justify-between border-b px-5 sm:h-[84px] sm:px-[5%]'>
        <div className='flex items-center gap-3 text-sm font-semibold sm:text-base'><BrandIcon className='size-9' /><span>财务自动化平台</span></div>
        <span className='text-xs text-muted-foreground'>平台维护</span>
      </header>
      <div className='mx-auto max-w-[666px] px-6 py-12 text-center sm:py-16'>
        <div className='mx-auto mb-7 grid h-20 w-20 place-items-center'><BrandIcon className='size-20' /></div>
        <p className='mb-3 text-sm text-primary'>平台维护</p>
        <h1 id='maintenance-title' className='mb-5 text-3xl font-semibold'>平台正在更新</h1>
        <p className='leading-8 text-muted-foreground'>当前暂时无法操作，请稍候。<br />更新完成后，页面会自动恢复。</p>
        <div className='my-8 rounded-2xl border border-border bg-card p-6 text-left'>
          <p className='font-medium'>正在更新平台服务</p><p className='mt-2 text-sm text-muted-foreground'>正在切换服务并检查运行状态。</p>
        </div>
        <p role='status' className='text-sm text-muted-foreground'>请保留当前页面，无需重新提交任务。</p>
      </div>
    </div>
  );
  return <div role='status' className='sticky top-0 z-[60] border-b border-[#e5d3c6] bg-[#f3e7df] px-6 py-3 text-sm text-[#624a3e]'>
    <p className='font-semibold'>{state.mode === 'worker' ? '任务服务正在更新' : '平台即将更新'}</p>
    <p className='mt-1'>{state.message}</p>
  </div>;
}
