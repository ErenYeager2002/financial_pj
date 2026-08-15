import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import type { SkillDetail } from '@/features/platform-api/types';
import { cn } from '@/lib/utils';

const riskLabels = {
  read_only: '只读或生成副本',
  write: '写入型',
  external_action: '外部操作'
} as const;

export function SkillCatalog({ skills }: { skills: SkillDetail[] }) {
  if (skills.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>暂无可用 Skill</CardTitle>
          <CardDescription>当前账号还没有获得已发布 Skill 的使用权限。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
      {skills.map((skill) => (
        <Card key={skill.id} className='h-full'>
          <CardHeader>
            <div className='mb-2 flex flex-wrap gap-2'>
              {skill.categories.map((category) => (
                <Badge key={category} variant='secondary'>
                  {category}
                </Badge>
              ))}
              <Badge variant='outline'>{riskLabels[skill.risk.level]}</Badge>
            </div>
            <CardTitle>{skill.name}</CardTitle>
            <CardDescription className='line-clamp-3'>{skill.description}</CardDescription>
            <CardAction>
              <Badge variant={skill.popular ? 'default' : 'outline'}>
                {skill.popular ? '常用' : `v${skill.version}`}
              </Badge>
            </CardAction>
          </CardHeader>
          <CardContent className='mt-auto space-y-2 text-sm'>
            <p>
              <span className='text-muted-foreground'>预计耗时：</span>
              {skill.estimated_minutes} 分钟
            </p>
            <p>
              <span className='text-muted-foreground'>输出结果：</span>
              {skill.output_summary}
            </p>
          </CardContent>
          <CardFooter className='justify-end'>
            <Link
              href={`/dashboard/skills/${skill.id}`}
              className={cn(buttonVariants({ variant: 'outline' }))}
            >
              查看详情
            </Link>
          </CardFooter>
        </Card>
      ))}
    </div>
  );
}
