import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { WorkflowDefinition } from '@/features/platform-api/types';
import { stepTypeLabel } from '@/features/workflows/step-display';

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  disabled: '已停用',
  superseded: '已替代',
  archived: '已归档'
};

interface WorkflowTopologyProps {
  definitions: WorkflowDefinition[];
}

export function WorkflowTopology({ definitions }: WorkflowTopologyProps): React.JSX.Element {
  return (
    <Card>
      <CardHeader>
        <CardTitle>受控执行流程</CardTitle>
        <CardDescription>节点配置和执行参数不会公开。</CardDescription>
      </CardHeader>
      <CardContent>
        {definitions.length ? (
          <div className='space-y-5'>
            {definitions.map((definition) => (
              <section key={definition.id} className='rounded-lg border p-4'>
                <div className='flex flex-wrap items-start justify-between gap-3'>
                  <div>
                    <h3 className='font-medium'>{definition.name}</h3>
                    <p className='text-sm text-muted-foreground'>
                      {definition.skill_id} · Skill v{definition.skill_version} · 流程 v
                      {definition.version}
                    </p>
                  </div>
                  <Badge variant='outline'>
                    {STATUS_LABELS[definition.status] ?? definition.status}
                  </Badge>
                </div>
                <ol className='mt-4 grid gap-3 lg:grid-cols-5'>
                  {(definition.steps ?? []).map((step, index) => (
                    <li key={step.id} className='relative rounded-lg border bg-muted/20 p-3'>
                      <div className='flex items-center gap-2'>
                        <span className='flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground'>
                          {index + 1}
                        </span>
                        <span className='font-medium'>{step.name}</span>
                      </div>
                      <p className='mt-2 text-xs text-muted-foreground'>
                        {stepTypeLabel(step.step_type)} · {step.worker_pool}
                      </p>
                      <p className='mt-1 text-xs text-muted-foreground'>
                        最多 {step.max_attempts} 次{step.retryable ? ' · 可重试' : ' · 不可重试'}
                      </p>
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          </div>
        ) : (
          <p className='text-muted-foreground'>当前部门还没有受控执行流程。</p>
        )}
      </CardContent>
    </Card>
  );
}
