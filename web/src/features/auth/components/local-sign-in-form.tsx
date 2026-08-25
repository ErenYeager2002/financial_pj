'use client';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
    <div className='w-full rounded-xl border bg-card p-6 text-card-foreground shadow-sm'>
      <div className='mb-6 space-y-1 text-center'>
        <h1 className='text-2xl font-semibold'>登录财务 Skill 平台</h1>
        <p className='text-sm text-muted-foreground'>请输入管理员分配的用户名和密码</p>
      </div>
      {error && (
        <Alert variant='destructive' className='mb-4'>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form className='space-y-4' onSubmit={submit}>
        <div className='space-y-2'>
          <Label htmlFor='sign-in-username'>用户名</Label>
          <Input
            id='sign-in-username'
            name='username'
            autoComplete='username'
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
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
            required
          />
        </div>
        <Button type='submit' size='lg' className='w-full' disabled={submitting}>
          {submitting ? '正在登录…' : '登录'}
        </Button>
      </form>
    </div>
  );
}
