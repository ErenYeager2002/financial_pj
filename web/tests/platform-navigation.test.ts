import assert from 'node:assert/strict';
import test from 'node:test';

import { getPlatformNavigation, getPlatformRouteTitle } from '../src/config/platform-navigation.ts';

function itemTitles(role: 'finance_user' | 'skill_admin'): string[] {
  return getPlatformNavigation(role).flatMap((group) =>
    group.items.flatMap((item) => [item.title, ...(item.items ?? []).map((child) => child.title)])
  );
}

function navigationSnapshot(role: 'finance_user' | 'skill_admin') {
  return getPlatformNavigation(role).map((group) => ({
    label: group.label,
    items: group.items.map((item) => ({
      title: item.title,
      url: item.url,
      items: item.items?.map((child) => ({ title: child.title, url: child.url })) ?? []
    }))
  }));
}

test('财务员工只看到完成任务所需的生产导航', () => {
  const groups = getPlatformNavigation('finance_user');

  assert.deepEqual(
    groups.map((group) => group.label),
    ['我的工作', '账号']
  );
  assert.deepEqual(itemTitles('finance_user'), [
    '工作台',
    '工具中心',
    'Skill 中心',
    '我的任务',
    '文件中心',
    'AI 助手',
    '个人资料'
  ]);
});

test('Skill 管理员额外看到治理入口', () => {
  const groups = getPlatformNavigation('skill_admin');

  assert.deepEqual(
    groups.map((group) => group.label),
    ['我的工作', '管理', '账号']
  );
  assert.deepEqual(itemTitles('skill_admin'), [
    '工作台',
    '工具中心',
    'Skill 中心',
    '我的任务',
    '文件中心',
    'AI 助手',
    'Skill 治理',
    '发布与维护',
    '用户与权限',
    '模型连接',
    '个人资料'
  ]);
});

test('生产导航不暴露模板演示模块', () => {
  const deniedTitles = [
    '产品管理',
    '任务看板',
    '在线沟通',
    '账单管理',
    '表单',
    '图标库',
    '专属功能',
    '数据查询示例'
  ];

  for (const role of ['finance_user', 'skill_admin'] as const) {
    const titles = itemTitles(role);
    for (const deniedTitle of deniedTitles) {
      assert.equal(titles.includes(deniedTitle), false, `${role} 不应看到 ${deniedTitle}`);
    }
  }
});

test('内部任务创建路由保留用户可读标题但不进入生产导航', () => {
  assert.equal(getPlatformRouteTitle('/dashboard/workflows'), '创建应收核销任务');
  assert.equal(
    getPlatformNavigation('finance_user')
      .flatMap((group) => group.items)
      .some((item) => item.url === '/dashboard/workflows'),
    false
  );
});

test('Skill 中心与 Skill 治理使用不同入口', () => {
  const groups = getPlatformNavigation('skill_admin');
  const items = groups.flatMap((group) => group.items);
  const skillCenter = items.find((item) => item.title === 'Skill 中心');
  const governance = items.find((item) => item.title === 'Skill 治理');
  const releaseMaintenance = governance?.items?.find((item) => item.title === '发布与维护');

  assert.equal(skillCenter?.url, '/dashboard/installed-skills');
  assert.equal(items.find((item) => item.title === '工具中心')?.url, '/dashboard/skills');
  assert.equal(releaseMaintenance?.url, '/dashboard/skill-governance');
  assert.notEqual(skillCenter?.url, releaseMaintenance?.url);
});

test('两种平台角色的菜单层级和链接符合生产规格', () => {
  assert.deepEqual(navigationSnapshot('finance_user'), [
    {
      label: '我的工作',
      items: [
        { title: '工作台', url: '/dashboard/overview', items: [] },
        { title: '工具中心', url: '/dashboard/skills', items: [] },
        { title: 'Skill 中心', url: '/dashboard/installed-skills', items: [] },
        { title: '我的任务', url: '/dashboard/runs', items: [] },
        { title: '文件中心', url: '/dashboard/files', items: [] },
        { title: 'AI 助手', url: '/dashboard/ai-chat', items: [] }
      ]
    },
    {
      label: '账号',
      items: [{ title: '个人资料', url: '/dashboard/profile', items: [] }]
    }
  ]);

  assert.deepEqual(navigationSnapshot('skill_admin'), [
    {
      label: '我的工作',
      items: [
        { title: '工作台', url: '/dashboard/overview', items: [] },
        { title: '工具中心', url: '/dashboard/skills', items: [] },
        { title: 'Skill 中心', url: '/dashboard/installed-skills', items: [] },
        { title: '我的任务', url: '/dashboard/runs', items: [] },
        { title: '文件中心', url: '/dashboard/files', items: [] },
        { title: 'AI 助手', url: '/dashboard/ai-chat', items: [] }
      ]
    },
    {
      label: '管理',
      items: [
        {
          title: 'Skill 治理',
          url: '#',
          items: [{ title: '发布与维护', url: '/dashboard/skill-governance' }]
        },
        { title: '用户与权限', url: '/dashboard/users', items: [] },
        { title: '模型连接', url: '/dashboard/model-connections', items: [] }
      ]
    },
    {
      label: '账号',
      items: [{ title: '个人资料', url: '/dashboard/profile', items: [] }]
    }
  ]);
});
