'use client';

import * as React from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import type { ServiceCredentialRead } from '@/features/platform-api/types';

interface ZhiyunCredentialCardProps {
  disabled?: boolean;
  onConfiguredChange?: (configured: boolean) => void;
}

function responseMessage(response: Response, fallback: string): Promise<string> {
  return response
    .json()
    .then((body: unknown) => {
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        return body.detail;
      }
      return fallback;
    })
    .catch(() => fallback);
}

function updatedLabel(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
}

export function ZhiyunCredentialCard({
  disabled = false,
  onConfiguredChange
}: ZhiyunCredentialCardProps): React.JSX.Element {
  const [status, setStatus] = React.useState<ServiceCredentialRead | null>(null);
  const [account, setAccount] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [showPassword, setShowPassword] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');
  const [activity, setActivity] = React.useState('');

  const loadStatus = React.useCallback(async () => {
    setLoading(true);
    setError('');
    onConfiguredChange?.(false);
    try {
      const response = await fetch('/api/platform/service-credentials/zhiyun', {
        cache: 'no-store'
      });
      if (!response.ok) {
        throw new Error(await responseMessage(response, '智云登录凭据状态加载失败。'));
      }
      const result = (await response.json()) as ServiceCredentialRead;
      setStatus(result);
      onConfiguredChange?.(result.configured);
    } catch (loadError) {
      setStatus(null);
      onConfiguredChange?.(false);
      setError(loadError instanceof Error ? loadError.message : '智云登录凭据状态加载失败。');
    } finally {
      setLoading(false);
    }
  }, [onConfiguredChange]);

  React.useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || disabled) return;
    const cleanAccount = account.trim();
    if (!cleanAccount || !password) {
      setError('请填写智云账号和密码。');
      return;
    }
    setSaving(true);
    setError('');
    setActivity('');
    try {
      const response = await fetch('/api/platform/service-credentials/zhiyun', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: cleanAccount, password })
      });
      if (!response.ok) {
        throw new Error(await responseMessage(response, '智云登录凭据保存失败。'));
      }
      const result = (await response.json()) as ServiceCredentialRead;
      setStatus(result);
      setAccount('');
      setPassword('');
      setShowPassword(false);
      setActivity(result.configured ? '智云登录凭据已安全保存。' : '智云登录凭据未能保存。');
      onConfiguredChange?.(result.configured);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '智云登录凭据保存失败。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className='rounded-lg border bg-muted/20 p-3'
      aria-labelledby='zhiyun-credential-title'
    >
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div>
          <h3 id='zhiyun-credential-title' className='flex items-center gap-2 text-sm font-medium'>
            <Icons.lock className='size-4' aria-hidden='true' />
            智云自动取数
          </h3>
          <p className='mt-1 text-xs text-muted-foreground'>
            账号和密码由开发端加密保存，只用于后台登录智云取数，页面不会再次显示密码。
          </p>
        </div>
        {loading ? (
          <Badge variant='outline'>正在检查…</Badge>
        ) : status?.configured ? (
          <Badge variant='secondary'>已配置</Badge>
        ) : (
          <Badge variant='destructive'>未配置</Badge>
        )}
      </div>

      {status?.configured && (
        <p className='mt-3 text-xs text-muted-foreground'>
          已保存账号：<span className='font-medium text-foreground'>{status.account_hint}</span>
          {updatedLabel(status.updated_at) ? ` · 更新于 ${updatedLabel(status.updated_at)}` : ''}
        </p>
      )}

      <form className='mt-3 grid gap-3 sm:grid-cols-2' onSubmit={(event) => void save(event)}>
        <label className='grid gap-1.5 text-sm font-medium'>
          智云账号
          <input
            name='zhiyun-account'
            type='text'
            autoComplete='username'
            className='h-11 rounded-md border bg-background px-3 font-normal outline-none focus-visible:ring-2 focus-visible:ring-ring'
            value={account}
            onChange={(event) => setAccount(event.target.value)}
            disabled={disabled || loading || saving}
            maxLength={255}
            placeholder={status?.configured ? '输入账号以更新凭据' : '请输入智云账号'}
          />
        </label>
        <label className='grid gap-1.5 text-sm font-medium'>
          智云密码
          <span className='relative'>
            <input
              name='zhiyun-password'
              type={showPassword ? 'text' : 'password'}
              autoComplete='current-password'
              className='h-11 w-full rounded-md border bg-background px-3 pr-16 font-normal outline-none focus-visible:ring-2 focus-visible:ring-ring'
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={disabled || loading || saving}
              maxLength={512}
              placeholder={status?.configured ? '输入密码以更新凭据' : '请输入智云密码'}
            />
            <button
              type='button'
              className='absolute inset-y-0 right-0 min-w-14 rounded-r-md px-2 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring'
              aria-label={showPassword ? '隐藏智云密码' : '显示智云密码'}
              aria-pressed={showPassword}
              onClick={() => setShowPassword((current) => !current)}
              disabled={disabled || loading || saving}
            >
              {showPassword ? '隐藏' : '显示'}
            </button>
          </span>
        </label>
        <div className='sm:col-span-2 flex flex-wrap items-center gap-3'>
          <Button
            type='submit'
            size='sm'
            disabled={disabled || loading || saving || !account.trim() || !password}
          >
            {saving ? '正在安全保存…' : status?.configured ? '更新账号密码' : '保存账号密码'}
          </Button>
          {status?.configured && (
            <span className='text-xs text-muted-foreground'>留空不会覆盖已保存的凭据。</span>
          )}
        </div>
      </form>

      {error && (
        <Alert variant='destructive' className='mt-3'>
          <AlertDescription className='flex flex-wrap items-center justify-between gap-2'>
            <span role='alert'>{error}</span>
            {!status && !loading && (
              <Button type='button' variant='outline' size='sm' onClick={() => void loadStatus()}>
                重新读取
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      {activity && (
        <p className='mt-3 text-sm text-emerald-700 dark:text-emerald-300' aria-live='polite'>
          {activity}
        </p>
      )}
    </section>
  );
}
