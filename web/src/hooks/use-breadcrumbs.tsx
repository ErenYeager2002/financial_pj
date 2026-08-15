'use client';

import { getPlatformRouteTitle } from '@/config/platform-navigation';
import { usePathname } from 'next/navigation';
import { useMemo } from 'react';

type BreadcrumbItem = {
  title: string;
  link: string;
};

// This allows to add custom title as well
const routeMapping: Record<string, BreadcrumbItem[]> = {
  '/dashboard': [{ title: '工作台', link: '/dashboard' }],
  '/dashboard/employee': [
    { title: '工作台', link: '/dashboard' },
    { title: '员工管理', link: '/dashboard/employee' }
  ],
  '/dashboard/product': [
    { title: '工作台', link: '/dashboard' },
    { title: '产品管理', link: '/dashboard/product' }
  ]
  // Add more custom mappings as needed
};

const segmentTitles: Record<string, string> = {
  dashboard: '工作台',
  team: '团队管理',
  product: '产品管理',
  kanban: '任务看板',
  chat: '在线沟通',
  forms: '表单',
  basic: '基础表单',
  'multi-step': '多步骤表单',
  'sheet-form': '抽屉与对话框',
  advanced: '高级表单',
  'react-query': '数据查询示例',
  elements: '功能组件',
  icons: '图标库',
  exclusive: '专属功能',
  billing: '账单管理'
};

export function useBreadcrumbs(): BreadcrumbItem[] {
  const pathname = usePathname();

  const breadcrumbs = useMemo(() => {
    // Check if we have a custom mapping for this exact path
    if (routeMapping[pathname]) {
      return routeMapping[pathname];
    }

    // If no exact match, fall back to generating breadcrumbs from the path
    const segments = pathname.split('/').filter(Boolean);
    return segments.map((segment, index) => {
      const path = `/${segments.slice(0, index + 1).join('/')}`;
      return {
        title: getPlatformRouteTitle(path) ?? segmentTitles[segment] ?? segment,
        link: path
      };
    });
  }, [pathname]);

  return breadcrumbs;
}
