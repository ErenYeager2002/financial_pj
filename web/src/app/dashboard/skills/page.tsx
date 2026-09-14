import PageContainer from '@/components/layout/page-container';
import { listSkillDedications } from '@/features/admin/api/skill-dedications';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import { listSkillSummaries } from '@/features/skills/api/server';
import { SkillCatalog } from '@/features/skills/components/skill-catalog';

export const metadata = {
  title: '工具中心'
};

export default async function Page(): Promise<React.JSX.Element> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  const [skills, dedications] = await Promise.all([
    listSkillSummaries(),
    session.role === 'skill_admin' ? listSkillDedications() : Promise.resolve([])
  ]);
  const adminDedications =
    session.role === 'skill_admin'
      ? Object.fromEntries(dedications.map((dedication) => [dedication.skill_id, dedication]))
      : undefined;

  return (
    <PageContainer
      pageTitle='工具中心' headingLevel={1} compact
    >
      <SkillCatalog skills={skills} adminDedications={adminDedications} />
    </PageContainer>
  );
}
