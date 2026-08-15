import PageContainer from '@/components/layout/page-container';
import { listApprovals } from '@/features/admin/api/approvals';
import { ApprovalManagement } from '@/features/admin/components/approval-management';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';

export const metadata = {
  title: '写入审批'
};

export default async function ApprovalsPage() {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    return (
      <PageContainer
        access={false}
        accessFallback={<p className='text-muted-foreground'>只有平台管理员可以查看写入审批。</p>}
      >
        {null}
      </PageContainer>
    );
  }
  const approvals = await listApprovals();
  return (
    <PageContainer
      pageTitle='写入任务审批'
      pageDescription='复核变更预览、执行快照和有效期；发起人不能审批自己的任务'
    >
      <ApprovalManagement session={session} initialApprovals={approvals} />
    </PageContainer>
  );
}
