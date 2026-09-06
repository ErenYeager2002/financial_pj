'use client';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';

export default function ChangePasswordForm({ mustChangePassword = false }: { mustChangePassword?: boolean }) {
  const router = useRouter();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致。');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        setError(body.detail || '密码修改失败，请重试。');
        return;
      }
      router.replace('/dashboard/overview');
      router.refresh();
    } catch {
      setError('密码修改服务暂时不可用，请稍后重试。');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className='w-full max-w-md rounded-xl border bg-card p-6 shadow-sm'>
      <div className='mb-6 space-y-1'>
        <h1 className='text-2xl font-semibold'>{mustChangePassword ? '修改初始密码' : '修改密码'}</h1>
        <p className='text-sm text-muted-foreground'>
          {mustChangePassword ? '完成修改后才能访问平台业务页面。' : '输入当前密码和新密码，保存后生效。'}
        </p>
      </div>
      {error && (
        <Alert variant='destructive' className='mb-4'>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form className='space-y-4' onSubmit={submit}>
        <div className='space-y-2'>
          <Label htmlFor='current-password'>当前密码</Label>
          <Input id='current-password' type='password' autoComplete='current-password' required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
        </div>
        <div className='space-y-2'>
          <Label htmlFor='new-password'>新密码</Label>
          <Input id='new-password' type='password' autoComplete='new-password' minLength={8} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
        </div>
        <div className='space-y-2'>
          <Label htmlFor='confirm-password'>再次输入新密码</Label>
          <Input id='confirm-password' type='password' autoComplete='new-password' minLength={8} required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
        </div>
        <Button type='submit' size='lg' className='w-full' disabled={submitting}>
          {submitting ? '正在保存…' : '修改密码'}
        </Button>
      </form>
    </div>
  );
}
