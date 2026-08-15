'use client';

import PageContainer from '@/components/layout/page-container';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useOrganization } from '@clerk/nextjs';
import { PricingTable } from '@clerk/nextjs';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Icons } from '@/components/icons';
import { billingInfoContent } from '@/config/infoconfig';

export default function BillingPage() {
  const { organization, isLoaded } = useOrganization();

  return (
    <PageContainer
      isLoading={!isLoaded}
      access={!!organization}
      accessFallback={
        <div className='flex min-h-[400px] items-center justify-center'>
          <div className='space-y-2 text-center'>
            <h2 className='text-2xl font-semibold'>尚未选择企业空间</h2>
            <p className='text-muted-foreground'>请选择或创建一个企业空间后查看账单信息。</p>
          </div>
        </div>
      }
      infoContent={billingInfoContent}
      pageTitle='账单与套餐'
      pageDescription={`管理 ${organization?.name ?? '当前企业空间'} 的订阅和用量限制`}
    >
      <div className='space-y-6'>
        {/* Info Alert */}
        <Alert>
          <Icons.info className='h-4 w-4' />
          <AlertDescription>
            套餐和订阅由 Clerk Billing 管理。订阅套餐后可使用对应功能和更高用量限制。
          </AlertDescription>
        </Alert>

        {/* Clerk Pricing Table */}
        <Card>
          <CardHeader>
            <CardTitle>可选套餐</CardTitle>
            <CardDescription>选择适合当前企业空间的套餐</CardDescription>
          </CardHeader>
          <CardContent>
            <div className='mx-auto max-w-4xl'>
              <PricingTable for='organization' />
            </div>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
