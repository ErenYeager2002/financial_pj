import { cn } from '@/lib/utils';

export function BrandIcon({ className }: { className?: string }) {
  return (
    <span aria-hidden='true' className={cn('relative inline-block size-8 shrink-0', className)}>
      <span className='absolute inset-0 bg-primary dark:bg-[color-mix(in_srgb,var(--primary),white_35%)]' style={{ mask: 'url(/brand/origami.png) center / contain no-repeat', WebkitMask: 'url(/brand/origami.png) center / contain no-repeat' }} />
      <span className='absolute inset-0' style={{ background: 'url(/brand/origami-shadow.png) center / contain no-repeat' }} />
    </span>
  );
}
