'use client';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { isClerkAPIResponseError } from '@clerk/nextjs/errors';
import { useSignIn } from '@clerk/nextjs/legacy';
import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, useState } from 'react';

type SignInStep = 'password' | 'email-code';

const DEFAULT_REDIRECT_URL = '/dashboard/overview';

function getErrorMessage(error: unknown) {
  if (!isClerkAPIResponseError(error)) {
    return '登录服务暂时不可用，请稍后重试。';
  }

  const code = error.errors[0]?.code;
  const messages: Record<string, string> = {
    form_identifier_not_found: '该邮箱尚未注册。',
    form_password_incorrect: '邮箱或密码错误。',
    form_password_pwned: '该密码存在安全风险，请先在 Clerk 中重置密码。',
    identifier_already_signed_in: '该账号已经登录，请刷新页面。',
    session_exists: '当前浏览器已经存在登录会话，请刷新页面。',
    too_many_requests: '尝试次数过多，请稍后再试。',
    user_locked: '账号已暂时锁定，请稍后再试。'
  };

  return (code && messages[code]) || error.errors[0]?.longMessage || '登录失败，请重试。';
}

function getSafeRedirectUrl(rawRedirectUrl: string | null) {
  if (!rawRedirectUrl || typeof window === 'undefined') {
    return DEFAULT_REDIRECT_URL;
  }

  try {
    const url = new URL(rawRedirectUrl, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/dashboard')) {
      return DEFAULT_REDIRECT_URL;
    }

    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return DEFAULT_REDIRECT_URL;
  }
}

export default function ClerkPasswordSignInForm() {
  const { isLoaded, signIn, setActive } = useSignIn();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [step, setStep] = useState<SignInStep>('password');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const finishSignIn = async (sessionId: string | null) => {
    if (!sessionId || !setActive) {
      throw new Error('Clerk did not return a session.');
    }

    await setActive({ session: sessionId });
    router.replace(getSafeRedirectUrl(searchParams.get('redirect_url')));
    router.refresh();
  };

  const prepareClientTrust = async () => {
    if (!signIn) return false;

    const emailFactor = signIn.supportedSecondFactors?.find(
      (factor) => factor.strategy === 'email_code'
    );

    if (!emailFactor || !('emailAddressId' in emailFactor)) {
      return false;
    }

    await signIn.prepareSecondFactor({
      strategy: 'email_code',
      emailAddressId: emailFactor.emailAddressId
    });
    setStep('email-code');
    return true;
  };

  const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isLoaded || !signIn) return;

    setError('');
    setIsSubmitting(true);

    try {
      const result = await signIn.create({
        strategy: 'password',
        identifier: email.trim(),
        password
      });

      if (result.status === 'complete') {
        await finishSignIn(result.createdSessionId);
        return;
      }

      if (result.status === 'needs_client_trust' || result.status === 'needs_second_factor') {
        if (await prepareClientTrust()) return;
      }

      setError('该账号需要其他验证方式，请联系管理员检查 Clerk 登录策略。');
    } catch (submitError) {
      setError(getErrorMessage(submitError));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCodeSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isLoaded || !signIn) return;

    setError('');
    setIsSubmitting(true);

    try {
      const result = await signIn.attemptSecondFactor({
        strategy: 'email_code',
        code: code.trim()
      });
      if (result.status === 'complete') {
        await finishSignIn(result.createdSessionId);
        return;
      }

      setError('验证码验证尚未完成，请重新输入。');
    } catch (submitError) {
      setError(getErrorMessage(submitError));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className='w-full rounded-xl border bg-card p-6 text-card-foreground shadow-sm'>
      <div className='mb-6 space-y-1 text-center'>
        <h1 className='text-2xl font-semibold'>登录财务自动化平台</h1>
        <p className='text-sm text-muted-foreground'>使用管理员邮箱和密码登录</p>
      </div>

      {error ? (
        <Alert variant='destructive' className='mb-4'>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {step === 'password' ? (
        <form className='space-y-4' onSubmit={handlePasswordSubmit}>
          <div className='space-y-2'>
            <Label htmlFor='sign-in-email'>邮箱</Label>
            <Input
              id='sign-in-email'
              name='email'
              type='email'
              autoComplete='username'
              placeholder='请输入邮箱地址'
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={isSubmitting}
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
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={isSubmitting}
              required
            />
          </div>
          <Button type='submit' size='lg' className='w-full' disabled={!isLoaded || isSubmitting}>
            {isSubmitting ? '正在登录...' : isLoaded ? '登录' : '正在连接登录服务...'}
          </Button>
        </form>
      ) : (
        <form className='space-y-4' onSubmit={handleCodeSubmit}>
          <p className='text-sm text-muted-foreground'>验证码已发送到管理员邮箱。</p>
          <div className='space-y-2'>
            <Label htmlFor='sign-in-code'>邮箱验证码</Label>
            <Input
              id='sign-in-code'
              name='code'
              type='text'
              inputMode='numeric'
              autoComplete='one-time-code'
              placeholder='请输入验证码'
              value={code}
              onChange={(event) => setCode(event.target.value)}
              disabled={isSubmitting}
              required
            />
          </div>
          <Button type='submit' size='lg' className='w-full' disabled={isSubmitting}>
            {isSubmitting ? '正在验证...' : '验证并登录'}
          </Button>
          <Button
            type='button'
            variant='ghost'
            className='w-full'
            onClick={() => {
              setStep('password');
              setCode('');
              setError('');
            }}
            disabled={isSubmitting}
          >
            返回重新登录
          </Button>
        </form>
      )}
    </div>
  );
}
