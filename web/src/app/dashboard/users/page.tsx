import PageContainer from '@/components/layout/page-container';
import { listAdminAuditEventPage, listAdminUsers } from '@/features/admin/api/server';
import { PlatformUserManagement } from '@/features/admin/components/platform-user-management';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import { listSkillCatalog } from '@/features/skills/api/server';

export const metadata = {
  title: '用户与权限'
};

type UsersPageProps = {
  searchParams: Promise<{
    tab?: string;
    audit_action?: string;
    audit_actor_id?: string;
    audit_resource_type?: string;
    audit_resource_id?: string;
    audit_created_from?: string;
    audit_created_to?: string;
  }>;
};

export default async function UsersPage({ searchParams }: UsersPageProps) {
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
  const raw = await searchParams;
  const auditFilters = {
    action: raw.audit_action?.trim().slice(0, 128) ?? '',
    actorId: raw.audit_actor_id?.trim().slice(0, 128) ?? '',
    resourceType: raw.audit_resource_type?.trim().slice(0, 64) ?? '',
    resourceId: raw.audit_resource_id?.trim().slice(0, 128) ?? '',
    createdFrom: raw.audit_created_from?.trim() ?? '',
    createdTo: raw.audit_created_to?.trim() ?? ''
  };
  const [users, skills, auditPage] = await Promise.all([
    listAdminUsers(),
    listSkillCatalog(),
    listAdminAuditEventPage({ ...auditFilters, limit: 20 })
  ]);
  return (
    <PageContainer pageTitle='用户、权限与审计'>
      <div className='space-y-4'>
        <PlatformUserManagement
          session={session}
          initialUsers={users}
          skills={skills}
          initialAuditPage={auditPage}
          initialAuditFilters={auditFilters}
          initialAuditTab={raw.tab === 'audit'}
        />
      </div>
    </PageContainer>
  );
}
