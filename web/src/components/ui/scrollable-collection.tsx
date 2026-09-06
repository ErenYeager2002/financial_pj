'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

interface ScrollableCollectionProps {
  ariaLabel: string;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
  followEnd?: boolean;
  resetScrollKey?: string;
}

export function ScrollableCollection({
  ariaLabel,
  children,
  className,
  contentClassName,
  followEnd = false,
  resetScrollKey
}: ScrollableCollectionProps): React.JSX.Element {
  const viewportRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!followEnd) return;
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [children, followEnd]);

  React.useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = 0;
  }, [resetScrollKey]);

  return (
    <div
      ref={viewportRef}
      role='region'
      aria-label={ariaLabel}
      className={cn(
        'max-h-[36rem] overflow-y-auto overscroll-contain rounded-lg pr-2 [scrollbar-gutter:stable] outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
        className
      )}
    >
      <div className={cn('min-w-0', contentClassName)}>{children}</div>
    </div>
  );
}
