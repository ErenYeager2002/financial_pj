import Link from 'next/link';
import { ConsolidationSetup } from '@/features/consolidation/components/consolidation-setup';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type {
  PlatformFile,
  SkillDedication,
  SkillDetail,
  TaskDraft
} from '@/features/platform-api/types';
import { SkillRunSetup } from '@/features/run-setup/components/skill-run-setup';
import { executionExperienceForSkill } from '@/features/skills/execution-experience';
import { cn } from '@/lib/utils';

interface SkillDetailViewProps {
  skill: SkillDetail;
  draft?: TaskDraft;
  draftFiles?: PlatformFile[];
  showExecution?: boolean;
  adminDedication?: SkillDedication;
}

function experienceHref(skillId: string, draftId?: string): string {
  const base = `/dashboard/skills/${encodeURIComponent(skillId)}/run`;
  return draftId ? `${base}?draft=${encodeURIComponent(draftId)}` : base;
}

export function SkillDetailView({
  skill,
  draft,
  draftFiles,
  showExecution = false,
  adminDedication
}: SkillDetailViewProps) {
  const experience = executionExperienceForSkill(skill.id);

  return (
    <div className='space-y-5'>
      <header className='grid gap-5 rounded-xl border bg-card p-5 lg:grid-cols-[minmax(0,1fr)_18rem]'>
        <div className='space-y-3'>
          {adminDedication && (
            <div className='flex flex-wrap gap-2'>
              <Badge
                variant={adminDedication.user_status === 'disabled' ? 'destructive' : 'outline'}
              >
                专属：{adminDedication.user_display_name}
                {adminDedication.user_status === 'disabled' ? '（已停用）' : ''}
              </Badge>
            </div>
          )}
          <div>
            <h2 className='text-xl font-semibold tracking-tight'>{skill.name}</h2>
            <p className='mt-2 max-w-3xl leading-7 text-muted-foreground'>{skill.description}</p>
          </div>
        </div>
        <div className='space-y-2 rounded-lg bg-muted/45 p-4'>
          <p className='text-sm font-medium'>完成后得到</p>
          <p className='text-sm leading-6 text-muted-foreground'>{skill.output_summary}</p>
          <p className='text-xs text-muted-foreground'>Skill 版本 {skill.version}</p>
        </div>
      </header>

      {!experience ? (
        <Alert variant='destructive'>
          <Icons.info />
          <AlertTitle>执行界面尚未配置</AlertTitle>
          <AlertDescription>
            该业务 Skill 不能使用通用表单创建任务。请由管理员完成专属执行体验配置后再运行。
          </AlertDescription>
        </Alert>
      ) : experience.family === 'workflow' ? (
        <Card>
          <CardHeader>
            <CardTitle>{experience.creationTitle}</CardTitle>
          </CardHeader>
          <CardContent className='space-y-4'>
            <p className='max-w-3xl text-sm leading-6 text-muted-foreground'>
              {experience.purpose} {experience.inputHint}
            </p>
            <Link
              href={`/dashboard/workflows?skill=${encodeURIComponent(skill.id)}`}
              className={cn(buttonVariants())}
            >
              {skill.action_label}
            </Link>
          </CardContent>
        </Card>
      ) : experience.classification === 'supporting' ? (
        <Card>
          <CardHeader>
            <CardTitle>{experience.creationTitle}</CardTitle>
          </CardHeader>
          <CardContent className='space-y-4'>
            <p className='text-sm leading-6 text-muted-foreground'>{experience.purpose}</p>
            {experience.supportHref && (
              <Link href={experience.supportHref} className={cn(buttonVariants())}>
                打开{experience.family === 'conversation' ? '对话' : '诊断'}界面
              </Link>
            )}
          </CardContent>
        </Card>
      ) : showExecution && skill.id === 'consolidated-statements' ? (
        <ConsolidationSetup />
      ) : showExecution ? (
        <SkillRunSetup
          skill={skill}
          experience={experience}
          draft={draft}
          draftFiles={draftFiles}
        />
      ) : (
        <section className='grid gap-4 rounded-xl border p-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center'>
          <div>
            <h3 className='font-medium'>{experience.creationTitle}</h3>
            <p className='mt-1 max-w-3xl text-sm leading-6 text-muted-foreground'>
              {experience.purpose}
            </p>
          </div>
          <Link href={experienceHref(skill.id, draft?.id)} className={cn(buttonVariants())}>
            准备{skill.action_label}
          </Link>
        </section>
      )}

      <div className='flex justify-end'>
        <Link href='/dashboard/skills' className={cn(buttonVariants({ variant: 'outline' }))}>
          返回工具中心
        </Link>
      </div>
    </div>
  );
}
