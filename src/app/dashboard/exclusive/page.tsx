'use client';

import PageContainer from '@/components/layout/page-container';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useOrganization, Show } from '@clerk/nextjs';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription } from '@/components/ui/alert';
import Link from 'next/link';

export default function ExclusivePage() {
  const { organization, isLoaded } = useOrganization();

  return (
    <PageContainer isLoading={!isLoaded}>
      <Show
        when={{ plan: 'pro' }}
        fallback={
          <div className='flex h-full items-center justify-center'>
            <Alert>
              <Icons.lock className='h-5 w-5 text-yellow-600' />
              <AlertDescription>
                <div className='mb-1 text-lg font-semibold'>需要专业版套餐</div>
                <div className='text-muted-foreground'>
                  此页面仅向订阅<span className='font-semibold'>专业版</span>套餐的企业空间开放。
                  <br />
                  请前往
                  <Link className='underline' href='/dashboard/billing'>
                    账单与套餐
                  </Link>
                  升级订阅。
                </div>
              </AlertDescription>
            </Alert>
          </div>
        }
      >
        <div className='space-y-6'>
          <div>
            <h1 className='flex items-center gap-2 text-3xl font-bold tracking-tight'>
              <Icons.badgeCheck className='h-7 w-7 text-green-600' />
              专业版专区
            </h1>
            <p className='text-muted-foreground'>
              欢迎，<span className='font-semibold'>{organization?.name}</span>
              ！此页面包含专业版企业空间可用的专属功能。
            </p>
          </div>
          <Card>
            <CardHeader>
              <CardTitle>欢迎使用专业版专区</CardTitle>
              <CardDescription>当前企业空间已订阅专业版套餐。</CardDescription>
            </CardHeader>
            <CardContent>
              <div className='text-lg'>你可以使用此处提供的全部专业版功能。</div>
            </CardContent>
          </Card>
        </div>
      </Show>
    </PageContainer>
  );
}
