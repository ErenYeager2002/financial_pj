'use client';
import { useQuery } from '@tanstack/react-query';

export function useMaterialEditLock(skillId: string) {
  const query = useQuery({
    queryKey: ['workflow-material-edit-state', skillId],
    enabled: Boolean(skillId),
    queryFn: async ({ signal }) => {
      const response = await fetch(`/api/platform/workflows/material-edit-state?skill_id=${encodeURIComponent(skillId)}`, { signal, cache: 'no-store' });
      if (!response.ok) throw new Error('无法核实材料编辑状态，请稍后重试。');
      const value = await response.json() as { locked?: unknown; reason?: unknown };
      if (typeof value.locked !== 'boolean') throw new Error('材料编辑状态无效。');
      return { locked: value.locked, reason: typeof value.reason === 'string' ? value.reason : '' };
    },
    staleTime: 0,
    refetchInterval: 3000,
    retry: 1
  });
  return {
    locked: Boolean(skillId) && (query.isPending || query.isError || query.data?.locked !== false),
    reason: query.isError ? '无法核实材料编辑状态，暂时不可修改。' : query.isPending ? '正在检查材料编辑状态…' : query.data?.reason ?? ''
  };
}
