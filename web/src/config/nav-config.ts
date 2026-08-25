import type { NavGroup, NavItem } from '@/types';
import {
  getPlatformNavigation,
  type PlatformNavigationItem,
  type PlatformRole
} from '@/config/platform-navigation';

function toNavItem(item: PlatformNavigationItem): NavItem {
  return {
    title: item.title,
    url: item.url,
    icon: item.icon,
    shortcut: item.shortcut,
    isActive: false,
    items: item.items?.map(toNavItem) ?? []
  };
}

export function getNavGroups(role: PlatformRole): NavGroup[] {
  return getPlatformNavigation(role).map((group) => ({
    id: group.id,
    label: group.label,
    items: group.items.map(toNavItem)
  }));
}
