export type PlatformRole = 'finance_user' | 'skill_admin';

export type PlatformNavigationIcon =
  | 'dashboard'
  | 'kanban'
  | 'forms'
  | 'clock'
  | 'page'
  | 'sparkles'
  | 'profile'
  | 'notification'
  | 'checks'
  | 'settings'
  | 'teams'
  | 'workspace';

export interface PlatformNavigationItem {
  title: string;
  url: string;
  icon: PlatformNavigationIcon;
  shortcut?: [string, string];
  items?: PlatformNavigationItem[];
}

export interface PlatformNavigationGroup {
  id: 'work' | 'todo' | 'management' | 'account';
  label: string;
  items: PlatformNavigationItem[];
}

const EMPLOYEE_GROUPS: PlatformNavigationGroup[] = [
  {
    id: 'work',
    label: '我的工作',
    items: [
      { title: '工作台', url: '/dashboard/overview', icon: 'dashboard', shortcut: ['d', 'd'] },
      { title: 'Skill 中心', url: '/dashboard/skills', icon: 'forms', shortcut: ['s', 'k'] },
      { title: '我的任务', url: '/dashboard/runs', icon: 'clock', shortcut: ['r', 'r'] },
      { title: '文件中心', url: '/dashboard/files', icon: 'page', shortcut: ['f', 'f'] },
      { title: 'AI 助手', url: '/dashboard/ai-chat', icon: 'sparkles', shortcut: ['a', 'i'] },
      {
        title: '后台任务',
        url: '/dashboard/workflows',
        icon: 'kanban',
        shortcut: ['w', 'f']
      }
    ]
  },
  {
    id: 'account',
    label: '账号',
    items: [
      { title: '个人资料', url: '/dashboard/profile', icon: 'profile', shortcut: ['m', 'm'] },
      {
        title: '消息通知',
        url: '/dashboard/notifications',
        icon: 'notification',
        shortcut: ['n', 'n']
      }
    ]
  }
];

const ADMIN_GROUPS: PlatformNavigationGroup[] = [
  EMPLOYEE_GROUPS[0],
  {
    id: 'management',
    label: '管理',
    items: [
      {
        title: 'Skill 治理',
        url: '#',
        icon: 'settings',
        items: [
          { title: '发布与维护', url: '/dashboard/skill-governance', icon: 'forms' },
          { title: '审核记录', url: '/dashboard/skill-reviews', icon: 'checks' }
        ]
      },
      {
        title: '用户与权限',
        url: '/dashboard/users',
        icon: 'teams',
        shortcut: ['u', 'u']
      },
      { title: '企业空间', url: '/dashboard/workspaces', icon: 'workspace' }
    ]
  },
  EMPLOYEE_GROUPS[1]
];

export function getPlatformNavigation(role: PlatformRole): PlatformNavigationGroup[] {
  return role === 'skill_admin' ? ADMIN_GROUPS : EMPLOYEE_GROUPS;
}

export function getPlatformRouteTitle(path: string): string | undefined {
  for (const group of ADMIN_GROUPS) {
    for (const item of group.items) {
      if (item.url === path) return item.title;
      const child = item.items?.find((candidate) => candidate.url === path);
      if (child) return child.title;
    }
  }
  return undefined;
}
