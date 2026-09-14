'use client';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { IconArrowRight, IconLoader2 } from '@tabler/icons-react';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';

interface LoginResponse {
  must_change_password: boolean;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    return body.detail || '登录失败，请重试。';
  } catch {
    return '登录服务暂时不可用，请稍后重试。';
  }
}

export default function LocalSignInForm() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password })
      });
      if (!response.ok) {
        setError(await errorMessage(response));
        return;
      }
      const session = (await response.json()) as LoginResponse;
      router.replace(
        session.must_change_password ? '/auth/change-password' : '/dashboard/overview'
      );
      router.refresh();
    } catch {
      setError('登录服务暂时不可用，请稍后重试。');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className='w-full min-w-0'>
      <div className='mb-8 space-y-2'>
        <h1 className='text-2xl font-semibold tracking-tight'>登录账号</h1>
        <p id='sign-in-description' className='text-sm leading-6 text-muted-foreground'>使用管理员分配的用户名和密码。</p>
      </div>
      {error && (
        <Alert id='sign-in-error' variant='destructive' className='mb-5' role='alert'>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form className='space-y-5' onSubmit={submit} aria-describedby='sign-in-description' aria-busy={submitting}>
        <div className='space-y-2'>
          <Label htmlFor='sign-in-username'>用户名</Label>
          <Input
            id='sign-in-username'
            name='username'
            autoComplete='username'
            autoCapitalize='none'
            spellCheck={false}
            placeholder='请输入用户名'
            className='h-11 rounded-lg text-base'
            aria-describedby={error ? 'sign-in-error' : undefined}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            disabled={submitting}
            required
          />
        </div>
        <div className='space-y-2'>
          <Label htmlFor='sign-in-password'>密码</Label>
          <Input
            id='sign-in-password'
            name='password'
            type='password'
            autoComplete='current-password'
            placeholder='请输入密码'
            className='h-11 rounded-lg text-base'
            aria-describedby={error ? 'sign-in-error' : undefined}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
            required
          />
        </div>
        <Button type='submit' size='lg' className='h-11 w-full rounded-lg bg-[color-mix(in_oklab,var(--primary)_80%,black)] text-primary-foreground hover:bg-[color-mix(in_oklab,var(--primary)_70%,black)]' disabled={submitting}>
          {submitting ? <IconLoader2 className='size-4 animate-spin motion-reduce:animate-none' aria-hidden='true' /> : null}
          {submitting ? '正在登录…' : '登录'}
          {!submitting ? <IconArrowRight className='size-4' aria-hidden='true' /> : null}
        </Button>
      </form>
      <p className='mt-6 border-t pt-5 text-xs leading-6 text-muted-foreground'>
        无法登录或忘记密码？请联系管理员。
      </p>
    </div>
  );
}
