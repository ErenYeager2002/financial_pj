export type BreadcrumbItem = {
  title: string;
  link: string;
};

const routeMapping: Record<string, BreadcrumbItem[]> = {
  '/dashboard': [{ title: '工作台', link: '/dashboard/overview' }],
  '/dashboard/overview': [{ title: '工作台', link: '/dashboard/overview' }]
};

const segmentTitles: Record<string, string> = {
  dashboard: '工作台'
};

const taskDetailBreadcrumbs: BreadcrumbItem[] = [
  { title: '工作台', link: '/dashboard/overview' },
  { title: '我的任务', link: '/dashboard/runs' }
];

export function buildBreadcrumbs(
  pathname: string,
  resolveRouteTitle: (path: string) => string | undefined = () => undefined
): BreadcrumbItem[] {
  if (/^\/dashboard\/workflows\/batches\/[^/]+$/.test(pathname)) {
    return [...taskDetailBreadcrumbs, { title: '批次详情', link: pathname }];
  }

  if (/^\/dashboard\/workflows\/[^/]+$/.test(pathname)) {
    return [...taskDetailBreadcrumbs, { title: '任务详情', link: pathname }];
  }

  if (/^\/dashboard\/runs\/[^/]+$/.test(pathname)) {
    return [...taskDetailBreadcrumbs, { title: '任务结果', link: pathname }];
  }

  if (/^\/dashboard\/skills\/[^/]+\/run$/.test(pathname)) {
    return [
      { title: '工作台', link: '/dashboard/overview' },
      { title: '工具中心', link: '/dashboard/skills' },
      { title: '创建财务任务', link: pathname }
    ];
  }

  if (routeMapping[pathname]) return routeMapping[pathname];

  const segments = pathname.split('/').filter(Boolean);
  return segments.map((segment, index) => {
    const path = `/${segments.slice(0, index + 1).join('/')}`;
    return {
      title: resolveRouteTitle(path) ?? segmentTitles[segment] ?? segment,
      link: path
    };
  });
}
