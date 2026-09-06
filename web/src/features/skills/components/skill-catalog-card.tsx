import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import type { SkillDedication, SkillSummary } from '@/features/platform-api/types';
import { cn } from '@/lib/utils';
import {
  skillCatalogActionFor,
  skillCatalogDetailHref,
  skillRiskLabels
} from '../skill-catalog-state';

interface SkillCatalogCardProps {
  skill: SkillSummary;
  dedication?: SkillDedication;
}

export function SkillCatalogCard({ skill, dedication }: SkillCatalogCardProps) {
  const action = skillCatalogActionFor(skill);

  return (
    <Card className='h-full min-w-0'>
      <CardHeader className='gap-2'>
        <div className='flex min-w-0 flex-wrap items-start justify-between gap-2'>
          <CardTitle className='min-w-0 flex-1 basis-40 break-words' title={skill.name}>
            {skill.name}
          </CardTitle>
          {dedication && (
            <Badge
              variant='outline'
              className='h-auto max-w-full shrink-0 py-1 text-muted-foreground whitespace-normal'
              title={`专属：${dedication.user_display_name}`}
            >
              <Icons.user aria-hidden='true' />
              <span className='min-w-0 break-words'>
                专属：{dedication.user_display_name}
                {dedication.user_status === 'disabled' ? '（已停用）' : ''}
              </span>
            </Badge>
          )}
        </div>
        <div className='flex flex-wrap gap-1.5' aria-label='操作和风险标签'>
          {skill.operation_labels.slice(0, 2).map((label, index) => (
            <Badge key={`operation-${index}-${label}`} variant='outline' className='h-auto max-w-full bg-muted/40 py-1 whitespace-normal'>
              {label}
            </Badge>
          ))}
          {skillRiskLabels(skill).map((label, index) => (
            <Badge key={`risk-${index}-${label}`} variant='outline' className='h-auto max-w-full py-1 whitespace-normal'>
              {label}
            </Badge>
          ))}
        </div>
      </CardHeader>

      <CardContent className='space-y-2 text-sm'>
        <p className='text-muted-foreground'>预计耗时：{skill.estimated_minutes} 分钟</p>
      </CardContent>

      <CardFooter className='mt-auto flex-wrap justify-between gap-2'>
        {action.kind === 'unavailable' ? (
          <Button type='button' disabled aria-disabled='true'>
            {action.label}
          </Button>
        ) : (
          <Link href={action.href} className={cn(buttonVariants(), 'platform-action')}>
            {action.label}
          </Link>
        )}
        <Link
          href={skillCatalogDetailHref(skill.id)}
          className={cn(buttonVariants({ variant: 'outline' }), 'platform-action')}
        >
          查看详情
        </Link>
      </CardFooter>
    </Card>
  );
}
