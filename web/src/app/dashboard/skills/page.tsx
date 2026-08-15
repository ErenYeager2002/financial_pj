import PageContainer from '@/components/layout/page-container';
import { listSkillCatalog } from '@/features/skills/api/server';
import { SkillCatalog } from '@/features/skills/components/skill-catalog';

export const metadata = {
  title: 'Skill 中心'
};

export default async function Page(): Promise<React.JSX.Element> {
  const skills = await listSkillCatalog();

  return (
    <PageContainer pageTitle='Skill 中心' pageDescription='查看并运行当前账号已获授权的财务 Skill'>
      <SkillCatalog skills={skills} />
    </PageContainer>
  );
}
