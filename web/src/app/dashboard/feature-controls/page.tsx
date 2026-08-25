import PageContainer from '@/components/layout/page-container';
import { listAdminUsers, listFeatureControls } from '@/features/admin/api/server';
import { FeatureControlList } from '@/features/admin/components/feature-control-list';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import { PlatformApiError } from '@/features/platform-api/errors';
import {
  getTaskReminderOwnerCredential,
  getTaskReminderSubscription
} from '@/features/task-reminders/api/server';
import { TaskReminderAssignment } from '@/features/task-reminders/components/task-reminder-assignment';

export const metadata = { title: '功能开关' };

export default async function FeatureControlsPage() {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    return (
      <PageContainer
        access={false}
        accessFallback={<p className='text-muted-foreground'>只有平台管理员可以查看功能开关。</p>}
      >
        {null}
      </PageContainer>
    );
  }
  const [controls, users, reminderSubscription] = await Promise.all([
    listFeatureControls(),
    listAdminUsers(),
    getTaskReminderSubscription('ar-hexiao-daily').catch((error: unknown) => {
      if (error instanceof PlatformApiError && error.status === 404) return null;
      throw error;
    })
  ]);
  const reminderCredential = reminderSubscription
    ? await getTaskReminderOwnerCredential('ar-hexiao-daily')
    : null;

  return (
    <PageContainer
      pageTitle='功能开关'
      pageDescription='统一查看和管理平台自动化、任务执行与登录认证状态'
    >
      <div className='space-y-4'>
        <FeatureControlList initialControls={controls} />
        <TaskReminderAssignment
          users={users}
          initialSubscription={reminderSubscription}
          initialCredential={reminderCredential}
        />
      </div>
    </PageContainer>
  );
}
