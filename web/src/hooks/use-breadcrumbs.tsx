'use client';

import { buildBreadcrumbs, type BreadcrumbItem } from '@/lib/breadcrumbs';
import { getPlatformRouteTitle } from '@/config/platform-navigation';
import { usePathname } from 'next/navigation';
import { useMemo } from 'react';

export function useBreadcrumbs(): BreadcrumbItem[] {
  const pathname = usePathname();

  const breadcrumbs = useMemo(() => {
    return buildBreadcrumbs(pathname, getPlatformRouteTitle);
  }, [pathname]);

  return breadcrumbs;
}
