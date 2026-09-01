import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { ScrollableCollection } from '@/components/ui/scrollable-collection';
import type { SkillDedication, SkillDetail } from '@/features/platform-api/types';
import { cn } from '@/lib/utils';

interface SkillCatalogProps {
  skills: SkillDetail[];
  adminDedications?: Record<string, SkillDedication>;
}

export function SkillCatalog({ skills, adminDedications }: SkillCatalogProps) {
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
    <ScrollableCollection
      ariaLabel='Skill 目录'
      contentClassName='grid gap-4 md:grid-cols-2 xl:grid-cols-3'
    >
      {skills.map((skill) => (
        <Card key={skill.id} className='h-full'>
          <CardHeader>
            {adminDedications?.[skill.id] && (
              <div className='mb-2 flex flex-wrap gap-2'>
                <Badge
                  variant={
                    adminDedications[skill.id].user_status === 'disabled'
                      ? 'destructive'
                      : 'outline'
                  }
                >
                  专属：{adminDedications[skill.id].user_display_name}
                  {adminDedications[skill.id].user_status === 'disabled' ? '（已停用）' : ''}
                </Badge>
              </div>
            )}
            <CardTitle>{skill.name}</CardTitle>
            <CardDescription className='line-clamp-3'>{skill.description}</CardDescription>
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
    </ScrollableCollection>
  );
}
