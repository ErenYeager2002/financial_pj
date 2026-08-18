import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { PlatformFile, SkillDetail, TaskDraft } from '@/features/platform-api/types';
import { SkillRunSetup } from '@/features/run-setup/components/skill-run-setup';
import { detailEntryForSkill } from '@/features/skills/detail-entry';
import { cn } from '@/lib/utils';

function inputProperties(skill: SkillDetail): Array<[string, Record<string, unknown>]> {
  const properties = skill.input_schema?.properties;
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return [];
  return Object.entries(properties).filter(
    (entry): entry is [string, Record<string, unknown>] =>
      typeof entry[1] === 'object' && entry[1] !== null && !Array.isArray(entry[1])
  );
}

function schemaText(property: Record<string, unknown>, fallback: string): string {
  const title = property.title;
  const description = property.description;
  if (typeof title === 'string' && title) return title;
  if (typeof description === 'string' && description) return description;
  return fallback;
}

interface SkillDetailViewProps {
  skill: SkillDetail;
  draft?: TaskDraft;
  draftFiles?: PlatformFile[];
}

export function SkillDetailView({ skill, draft, draftFiles }: SkillDetailViewProps) {
  const detailEntry = detailEntryForSkill(skill);
  const properties = inputProperties(skill);
  const required = Array.isArray(skill.input_schema?.required)
    ? new Set(
        skill.input_schema.required.filter((item): item is string => typeof item === 'string')
      )
    : new Set<string>();

  return (
    <div className='space-y-4'>
      <Card>
        <CardHeader>
          <div className='flex flex-wrap gap-2'>
            {skill.categories.map((category) => (
              <Badge key={category} variant='secondary'>
                {category}
              </Badge>
            ))}
            <Badge variant='outline'>v{skill.version}</Badge>
            <Badge variant='outline'>{skill.estimated_minutes} 分钟</Badge>
          </div>
          <CardTitle className='text-xl'>{skill.name}</CardTitle>
        </CardHeader>
        <CardContent className='space-y-3'>
          <p className='text-muted-foreground'>{skill.description}</p>
          <p>
            <span className='font-medium'>预期结果：</span>
            {skill.output_summary}
          </p>
          <p className='text-sm text-muted-foreground'>
            所有任务都需要确认参数和文件后才能创建。当前页面不会直接启动 Worker。
          </p>
        </CardContent>
      </Card>

      <div className='grid gap-4 lg:grid-cols-2'>
        <Card>
          <CardHeader>
            <CardTitle>所需文件</CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            {(skill.file_inputs ?? []).length === 0 ? (
              <p className='text-muted-foreground'>此 Skill 不需要上传文件。</p>
            ) : (
              skill.file_inputs?.map((input) => (
                <div key={input.role} className='rounded-lg border p-3'>
                  <div className='flex items-center justify-between gap-3'>
                    <span className='font-medium'>{input.name}</span>
                    <Badge variant={input.required ? 'default' : 'outline'}>
                      {input.required ? '必需' : '可选'}
                    </Badge>
                  </div>
                  {input.description && (
                    <p className='mt-1 text-sm text-muted-foreground'>{input.description}</p>
                  )}
                  <p className='mt-2 text-xs text-muted-foreground'>
                    支持：
                    {(input.extensions ?? []).length
                      ? (input.extensions ?? []).join('、')
                      : '未限制格式'}
                    {input.multiple ? '；可上传多个文件' : '；单个文件'}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>参数与处理进度</CardTitle>
          </CardHeader>
          <CardContent className='space-y-4'>
            <div className='space-y-2'>
              {properties.length === 0 ? (
                <p className='text-muted-foreground'>此 Skill 没有额外参数。</p>
              ) : (
                properties.map(([name, property]) => (
                  <div
                    key={name}
                    className='flex items-center justify-between rounded-lg border p-3'
                  >
                    <span>{schemaText(property, name)}</span>
                    <Badge variant={required.has(name) ? 'default' : 'outline'}>
                      {required.has(name) ? '必填' : '可选'}
                    </Badge>
                  </div>
                ))
              )}
            </div>
            {(skill.progress_stages ?? []).length > 0 && (
              <ol className='space-y-2 border-t pt-4'>
                {skill.progress_stages?.map((stage, index) => (
                  <li key={stage.key} className='flex gap-3 text-sm'>
                    <span className='flex size-6 shrink-0 items-center justify-center rounded-full bg-muted'>
                      {index + 1}
                    </span>
                    <span className='pt-0.5'>{stage.label}</span>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>

      {detailEntry === 'workflow' ? (
        <Card>
          <CardHeader>
          <CardTitle>进入后台任务</CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            <p className='text-sm text-muted-foreground'>
              这个 Skill 需要由后台 Worker 处理日期、文件和写入确认，不能从标准任务向导启动。
            </p>
            <Link
              href={`/dashboard/workflows?skill=${encodeURIComponent(skill.id)}`}
              className={cn(buttonVariants())}
            >
              创建后台任务
            </Link>
          </CardContent>
        </Card>
      ) : (
        <SkillRunSetup skill={skill} draft={draft} draftFiles={draftFiles} />
      )}

      <div className='flex items-center justify-between rounded-lg border bg-muted/30 p-4'>
        <p className='text-sm text-muted-foreground'>任务创建后可在本页查看任务编号和队列状态。</p>
        <Link href='/dashboard/skills' className={cn(buttonVariants({ variant: 'outline' }))}>
          返回目录
        </Link>
      </div>
    </div>
  );
}
