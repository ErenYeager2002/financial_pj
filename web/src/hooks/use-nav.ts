'use client';

import { useMemo } from 'react';
import type { NavGroup, NavItem } from '@/types';

// 角色和权限已经由服务端导航配置及 FastAPI 接口决定；客户端只保留兼容的纯展示接口。
export function useFilteredNavItems(items: NavItem[]): NavItem[] {
  return useMemo(() => items, [items]);
}

export function useFilteredNavGroups(groups: NavGroup[]): NavGroup[] {
  return useMemo(() => groups, [groups]);
}
