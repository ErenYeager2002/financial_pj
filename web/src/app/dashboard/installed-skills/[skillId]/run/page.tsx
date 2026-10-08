import { nativeSkillDisplay } from '@/features/skills/native-skill-display';
import { notFound } from 'next/navigation';
import PageContainer from '@/components/layout/page-container';
import type { PiSession } from '@/features/pi-runtime/pi-workspace';
import { PiChat } from '@/features/pi-runtime/pi-chat';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { PlatformApiError } from '@/features/platform-api/errors';
import type { NativeSkillRead } from '@/features/platform-api/generated';
import type { PlatformSession } from '@/features/platform-api/types';
export const metadata = { title: 'Skill 对话' };
export default async function Page({ params, searchParams }: { params: Promise<{ skillId: string }>; searchParams: Promise<{session?:string}> }) {
  const [{skillId}, query] = await Promise.all([params, searchParams]);
  let skill: NativeSkillRead;
  try { skill = await platformServerRequest<NativeSkillRead>(`/api/native-skills/${encodeURIComponent(skillId)}`); }
  catch (error) { if (error instanceof PlatformApiError && error.status === 404) notFound(); throw error; }
  const [sessions, account] = await Promise.all([
    platformServerRequest<PiSession[]>('/api/pi-runtime/sessions'),
    platformServerRequest<PlatformSession>('/api/session')
  ]);
  const storageScope = `${account.user_id}:${account.department_id}`;
  const display = nativeSkillDisplay(skill.id, skill.name, skill.description);
  return <PageContainer pageTitle={display.name} headingLevel={1} compact>
    <p className='text-muted-foreground mb-4 text-sm'>{display.description}</p>
    <PiChat key={storageScope} storageScope={storageScope} skillId={skill.id} initialSessions={sessions.filter(item=>item.skill_id===skill.id)} initialSessionId={query.session} />
  </PageContainer>;
}
