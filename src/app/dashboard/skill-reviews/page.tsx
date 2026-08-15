import PageContainer from '@/components/layout/page-container';
import { listSkillReleases } from '@/features/admin/api/skill-releases';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import { SkillReleaseManagement } from '@/features/skills/components/skill-release-management';

export const metadata = {
  title: 'Skill 审核记录'
};

export default async function SkillReviewsPage() {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    return (
      <PageContainer
        access={false}
        accessFallback={
          <p className='text-muted-foreground'>只有平台管理员可以查看 Skill 审核记录。</p>
        }
      >
        {null}
      </PageContainer>
    );
  }

  const releases = await listSkillReleases();
  return (
    <PageContainer
      pageTitle='Skill 审核记录'
      pageDescription='集中处理待审核版本，并查看已发布版本与历史审核结果'
    >
      <SkillReleaseManagement initialReleases={releases} view='records' />
    </PageContainer>
  );
}
