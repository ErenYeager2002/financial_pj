import { Skeleton } from '@/components/ui/skeleton';

export function SkillGovernanceSkeleton(): React.JSX.Element {
  return (
    <div className='space-y-6' aria-label='正在加载工作流与运行观测'>
      <Skeleton className='h-72 w-full' />
      <Skeleton className='h-64 w-full' />
    </div>
  );
}
