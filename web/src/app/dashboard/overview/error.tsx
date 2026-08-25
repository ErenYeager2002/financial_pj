'use client';

import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Icons } from '@/components/icons';
import { useRouter } from 'next/navigation';
import { useEffect, useTransition } from 'react';
import * as Sentry from '@sentry/nextjs';

export default function OverviewError({ error, reset }: { error: Error; reset: () => void }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  // Defer the refresh until the next render phase so React settles pending states first
  const retry = () => {
    startTransition(() => {
      router.refresh();
      reset();
    });
  };

  return (
    <Alert variant='destructive'>
      <AlertTitle>工作台加载失败</AlertTitle>
      <AlertDescription className='flex items-center justify-between gap-4'>
        <span>{error.message}</span>
        <span className='flex items-center gap-2'>
          <Button variant='outline' size='sm' onClick={retry} disabled={isPending}>
            {isPending ? (
              <>
                <Icons.spinner className='mr-2 h-4 w-4 animate-spin' aria-hidden='true' />
                正在重试...
              </>
            ) : (
              '重试'
            )}
          </Button>
          <span role='status' aria-live='polite' className='sr-only'>
            {isPending ? '正在重试' : ''}
          </span>
        </span>
      </AlertDescription>
    </Alert>
  );
}
