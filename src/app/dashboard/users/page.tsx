import PageContainer from '@/components/layout/page-container';
import { listAdminAuditEvents, listAdminUsers } from '@/features/admin/api/server';
import { PlatformUserManagement } from '@/features/admin/components/platform-user-management';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import { listSkillCatalog } from '@/features/skills/api/server';

export const metadata = {
  title: '用户与权限'
};

export default async function UsersPage() {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    return (
      <PageContainer
        access={false}
        accessFallback={<p className='text-muted-foreground'>只有平台管理员可以查看用户与权限。</p>}
      >
        {null}
      </PageContainer>
    );
  }
  const [users, skills, auditEvents] = await Promise.all([
    listAdminUsers(),
    listSkillCatalog(),
    listAdminAuditEvents('', '', 100)
  ]);
  return (
    <PageContainer
      pageTitle='用户、权限与审计'
      pageDescription='管理本部门平台账号、固定角色、Skill 权限和脱敏审计记录'
    >
      <PlatformUserManagement
        session={session}
        initialUsers={users}
        skills={skills}
        initialAuditEvents={auditEvents}
      />
    </PageContainer>
  );
}
