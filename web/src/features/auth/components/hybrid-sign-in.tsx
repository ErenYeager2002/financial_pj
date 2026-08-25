'use client';

import { Button } from '@/components/ui/button';
import { useState } from 'react';
import ClerkPasswordSignInForm from './clerk-password-sign-in-form';
import LocalSignInForm from './local-sign-in-form';

export default function HybridSignIn() {
  const [provider, setProvider] = useState<'clerk' | 'session'>('clerk');
  return (
    <div className='w-full space-y-3'>
      <div className='grid grid-cols-2 gap-2 rounded-lg border bg-muted/40 p-1'>
        <Button type='button' variant={provider === 'clerk' ? 'default' : 'ghost'} onClick={() => setProvider('clerk')}>Clerk 登录</Button>
        <Button type='button' variant={provider === 'session' ? 'default' : 'ghost'} onClick={() => setProvider('session')}>本地账号</Button>
      </div>
      {provider === 'clerk' ? <ClerkPasswordSignInForm /> : <LocalSignInForm />}
    </div>
  );
}
