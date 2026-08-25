'use client';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { UserAvatarProfile } from '@/components/user-avatar-profile';
import type { PlatformSession } from '@/features/platform-api/types';
import { platformAvatarUrl, platformAvatarUser } from '@/features/profile/avatar';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';

const MAX_AVATAR_BYTES = 2 * 1024 * 1024;
const ACCEPTED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export function AvatarUpload({ session }: { session: PlatformSession }) {
  const router = useRouter();
  const [avatarUrl, setAvatarUrl] = useState(platformAvatarUrl(session));
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage('');
    setError('');
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const upload = form.get('upload');
    if (!(upload instanceof File) || upload.size === 0) {
      setError('请选择头像图片。');
      return;
    }
    if (!ACCEPTED_TYPES.has(upload.type)) {
      setError('头像仅支持 JPEG、PNG 或 WebP 图片。');
      return;
    }
    if (upload.size > MAX_AVATAR_BYTES) {
      setError('头像文件不能超过 2 MB。');
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch('/api/platform/profile/avatar', {
        method: 'POST',
        body: form
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        setError(body?.detail || '头像上传失败。');
        return;
      }
      const nextSession = (await response.json()) as PlatformSession;
      setAvatarUrl(platformAvatarUrl(nextSession));
      setMessage('头像已更新。');
      formElement.reset();
      router.refresh();
    } catch {
      setError('头像上传失败，请稍后重试。');
    } finally {
      setSubmitting(false);
    }
  }

  const user = { ...platformAvatarUser(session), imageUrl: avatarUrl };
  return (
    <div className='space-y-4'>
      <div className='flex items-center gap-4'>
        <UserAvatarProfile
          className='size-16 [&_[data-slot=avatar-fallback]]:text-xl'
          user={user}
        />
        <div>
          <h1 className='text-xl font-semibold'>{session.display_name}</h1>
          <p className='text-muted-foreground mt-1 text-sm'>JPEG、PNG 或 WebP，最大 2 MB</p>
        </div>
      </div>
      <form className='flex flex-col gap-3 sm:flex-row sm:items-center' onSubmit={submit}>
        <Input
          aria-label='选择头像图片'
          name='upload'
          type='file'
          accept='image/jpeg,image/png,image/webp'
          disabled={submitting}
          required
        />
        <Button type='submit' disabled={submitting}>
          {submitting ? '上传中…' : '上传头像'}
        </Button>
      </form>
      {error && (
        <Alert variant='destructive'>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {message && (
        <Alert>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
