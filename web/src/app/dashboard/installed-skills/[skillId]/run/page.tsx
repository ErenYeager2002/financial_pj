import { nativeSkillDisplay } from '@/features/skills/native-skill-display';
import { notFound } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import { getAssistantStatus, getAdminAssistantProfile, listAdminModelConnections } from '@/features/ai-chat/api/server';
import { AssistantWorkspace } from '@/features/ai-chat/components/assistant-workspace';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { PlatformApiError } from '@/features/platform-api/errors';
import type { PlatformSession } from '@/features/platform-api/types';
import type { NativeSkillRead, FileInputSpec } from '@/features/platform-api/generated';
export const metadata = { title: 'Skill 对话' };
export default async function Page({ params }: { params: Promise<{ skillId: string }> }) {
  const { skillId } = await params;
  let skill: NativeSkillRead;
  try { skill = await platformServerRequest<NativeSkillRead>(`/api/native-skills/${encodeURIComponent(skillId)}`); }
  catch (error) { if (error instanceof PlatformApiError && error.status === 404) notFound(); throw error; }
  const [status, session] = await Promise.all([getAssistantStatus(), platformServerRequest<PlatformSession>('/api/session')]);
  const isAdmin = session.role === 'skill_admin';
  const [profile, connections] = isAdmin ? await Promise.all([getAdminAssistantProfile(), listAdminModelConnections()]) : [undefined, undefined];
  const inputs: FileInputSpec[] = [{ role: 'materials', name: '任务材料', description: '当前任务需要的材料', required: false, extensions: [], multiple: true, min_files: 0, max_size_mb: null }];
  const display = nativeSkillDisplay(skill.id, skill.name, skill.description);
  return <PageContainer pageTitle={display.name} headingLevel={1} compact><p className="text-xs text-muted-foreground break-all">{skill.id} · {display.description}</p><AssistantWorkspace skillId={`native--${skill.id}`} skillName={display.name} fileInputs={inputs} initialConfigured={status.configured} initialModel={status.model} isAdmin={isAdmin} profile={profile} connections={connections} /></PageContainer>;
}
