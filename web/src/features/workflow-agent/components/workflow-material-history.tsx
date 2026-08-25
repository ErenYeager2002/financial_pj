'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  workflowMaterialKeys,
  workflowMaterialSetsQueryOptions
} from '@/features/workflow-agent/api/queries';
import { restoreWorkflowMaterialSetVersion } from '@/features/workflow-agent/api/service';
import type { WorkflowMaterialSet } from '@/features/platform-api/types';
import { formatDate } from '@/lib/format';

interface WorkflowMaterialHistoryProps {
  skillId: string;
  allowRestore?: boolean;
}

export function WorkflowMaterialHistory({
  skillId,
  allowRestore = false
}: WorkflowMaterialHistoryProps): React.JSX.Element {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = React.useState(false);
  const materialQuery = useQuery({
    ...workflowMaterialSetsQueryOptions(skillId),
    enabled: expanded
  });
  const versions = materialQuery.data ?? [];
  const restoreMutation = useMutation({
    mutationFn: (materialSetId: string) =>
      restoreWorkflowMaterialSetVersion(skillId, materialSetId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workflowMaterialKeys.skill(skillId) });
      router.refresh();
    }
  });

  const visibleVersions = allowRestore
    ? versions
    : versions.filter((version) => version.state === 'current').slice(0, 1);

  async function restore(version: WorkflowMaterialSet) {
    if (
      restoreMutation.isPending ||
      !window.confirm(
        `确认把 V${version.version} 的文件组合恢复为新的当前版本吗？历史版本不会被修改。`
      )
    ) {
      return;
    }
    await restoreMutation.mutateAsync(version.id);
  }

  const error = materialQuery.error ?? restoreMutation.error;
  const loading = materialQuery.isFetching;

  return (
    <details
      className='rounded-md border bg-muted/10'
      data-testid='workflow-material-history'
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className='cursor-pointer list-none px-3 py-2 text-sm font-medium'>
        {allowRestore ? '查看业务材料版本历史' : '查看当前业务材料'}
        {loading ? '（加载中…）' : allowRestore ? `（${versions.length} 个版本）` : ''}
      </summary>
      <div className='space-y-3 border-t p-3'>
        {error && (
          <p className='text-sm text-destructive'>
            {error instanceof Error ? error.message : '业务材料版本加载失败。'}
          </p>
        )}
        {!loading && versions.length === 0 && (
          <p className='text-sm text-muted-foreground'>尚未建立业务材料版本。</p>
        )}
        {visibleVersions.map((version) => (
          <section key={version.id} className='rounded-md border bg-background p-3'>
            <div className='flex flex-wrap items-start justify-between gap-2'>
              <div className='flex flex-wrap items-center gap-2'>
                <span className='font-medium'>V{version.version}</span>
                {version.state === 'current' ? (
                  <Badge>当前版本</Badge>
                ) : (
                  <Badge variant='outline'>历史版本</Badge>
                )}
                <span className='text-xs text-muted-foreground'>
                  发布于 {formatDate(version.published_at, { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              {allowRestore && version.state !== 'current' && (
                <Button
                  type='button'
                  size='sm'
                  variant='outline'
                  disabled={restoreMutation.isPending}
                  onClick={() => void restore(version)}
                >
                  {restoreMutation.isPending && restoreMutation.variables === version.id
                    ? '恢复中…'
                    : '恢复为新版本'}
                </Button>
              )}
            </div>
            <p className='mt-1 text-xs text-muted-foreground'>
              来源任务：
              {version.source_workflow_display_id ||
                version.source_workflow_id ||
                '首次上传或人工指定'}
            </p>
            <div className='mt-2 space-y-2'>
              {(version.files ?? []).map((file) => (
                <div key={`${version.id}-${file.role}-${file.year ?? 0}`} className='text-xs'>
                  <p>
                    {file.role === 'profit_loss_ledgers'
                      ? `${file.year ?? '未知'} 年盈亏核算表`
                      : '到账流转表'}
                    ：{file.name}
                  </p>
                  {allowRestore && (
                    <p className='break-all font-mono text-muted-foreground'>
                      SHA-256 {file.sha256}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </details>
  );
}
