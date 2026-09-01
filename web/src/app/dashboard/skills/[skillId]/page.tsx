import { notFound } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import { listSkillDedications } from '@/features/admin/api/skill-dedications';
import { getTaskDraft } from '@/features/ai-chat/api/server';
import { getFile } from '@/features/files/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession, SkillDetail } from '@/features/platform-api/types';
import { getSkillCatalogItem } from '@/features/skills/api/server';
import { SkillDetailView } from '@/features/skills/components/skill-detail';

export const metadata = {
  title: 'Skill 详情'
};

type PageProps = {
  params: Promise<{ skillId: string }>;
  searchParams: Promise<{ draft?: string }>;
};

export default async function Page({ params, searchParams }: PageProps) {
  const { skillId } = await params;
  const { draft: draftId } = await searchParams;
  const session = await platformServerRequest<PlatformSession>('/api/session');
  let skill: SkillDetail;
  let draft;
  let draftFiles;
  let adminDedication;
  try {
    const [loadedSkill, dedications] = await Promise.all([
      getSkillCatalogItem(skillId),
      session.role === 'skill_admin' ? listSkillDedications() : Promise.resolve([])
    ]);
    skill = loadedSkill;
    adminDedication =
      session.role === 'skill_admin'
        ? dedications.find((dedication) => dedication.skill_id === skill.id)
        : undefined;
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
    <PageContainer pageTitle='Skill 详情'>
      <SkillDetailView
        skill={skill}
        draft={draft}
        draftFiles={draftFiles}
        adminDedication={adminDedication}
      />
    </PageContainer>
  );
}
