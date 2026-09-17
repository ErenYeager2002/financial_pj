import { nativeSkillDisplay } from '@/features/skills/native-skill-display';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import type { NativeSkillRead } from '@/features/platform-api/generated';
import { SkillInstallCatalogView } from '@/features/skills/components/skill-install-catalog';
import { Card, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card';
import { buttonVariants } from '@/components/ui/button';
export const metadata = { title: 'Skill 中心' };
export default async function Page() {
  const [session, skills] = await Promise.all([
    platformServerRequest<PlatformSession>('/api/session'), platformServerRequest<NativeSkillRead[]>('/api/native-skills')
  ]);
  return <PageContainer pageTitle='Skill 中心' headingLevel={1} compact>
    <div className='space-y-6'>
      <p className='text-sm text-muted-foreground'>从仓库直接安装 Skill，通过 AI 对话运行。现有工具保留在工具中心。</p>
      {skills.length ? <div className='platform-skill-grid'>{skills.map(skill => { const display = nativeSkillDisplay(skill.id, skill.name, skill.description); return <Card key={skill.id}>
        <CardHeader><CardTitle>{display.name}</CardTitle><p className='text-xs text-muted-foreground break-all'>{skill.id}</p><CardDescription>{display.description}</CardDescription></CardHeader>
        <CardFooter className='mt-auto flex justify-between gap-2'><Link className={buttonVariants()} href={`/dashboard/installed-skills/${encodeURIComponent(skill.id)}/run`}>开始对话</Link><span className='text-xs text-muted-foreground'>{skill.commit.slice(0,12)}</span></CardFooter>
      </Card>; })}</div> : <div className='rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground'>暂无已安装的 Skill</div>}
      {session.role === 'skill_admin' && <SkillInstallCatalogView />}
    </div>
  </PageContainer>;
}
