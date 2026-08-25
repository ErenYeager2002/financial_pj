import { notFound } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import { getTaskDraft } from '@/features/ai-chat/api/server';
import { getFile } from '@/features/files/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { getSkillCatalogItem } from '@/features/skills/api/server';
import { SkillDetailView } from '@/features/skills/components/skill-detail';

export const metadata = {
  title: '运行 Skill'
};

type PageProps = {
  params: Promise<{ skillId: string }>;
  searchParams: Promise<{ draft?: string }>;
};

export default async function Page({ params, searchParams }: PageProps) {
  const { skillId } = await params;
  const { draft: draftId } = await searchParams;
  let skill;
  let draft;
  let draftFiles;

  try {
    skill = await getSkillCatalogItem(skillId);
    if (draftId) {
      draft = await getTaskDraft(draftId);
      if (draft.skill_id !== skill.id || !['draft', 'ready'].includes(draft.state)) notFound();
      const fileIds = new Set<string>();
      for (const value of Object.values(draft.files ?? {})) {
        const ids = Array.isArray(value) ? value : value ? [value] : [];
        ids.forEach((id) => fileIds.add(id));
      }
      draftFiles = await Promise.all([...fileIds].map((fileId) => getFile(fileId)));
    }
  } catch (error) {
    if (error instanceof PlatformApiError && error.status === 404) notFound();
    throw error;
  }

  return (
    <PageContainer pageTitle='执行 Skill' pageDescription='按当前业务流程准备材料并创建任务'>
      <SkillDetailView skill={skill} draft={draft} draftFiles={draftFiles} showExecution />
    </PageContainer>
  );
}
