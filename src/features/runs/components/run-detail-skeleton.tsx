import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function RunDetailSkeleton(): React.JSX.Element {
  return (
    <div className='space-y-4' aria-label='正在加载任务详情'>
      <Card>
        <CardHeader className='space-y-3'>
          <Skeleton className='h-5 w-40' />
          <Skeleton className='h-7 w-64' />
          <Skeleton className='h-4 w-80 max-w-full' />
        </CardHeader>
        <CardContent className='space-y-4'>
          <Skeleton className='h-8 w-full' />
          <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton key={index} className='h-12 w-full' />
            ))}
          </div>
        </CardContent>
      </Card>
      <Skeleton className='h-72 w-full' />
      <Skeleton className='h-48 w-full' />
    </div>
  );
}
