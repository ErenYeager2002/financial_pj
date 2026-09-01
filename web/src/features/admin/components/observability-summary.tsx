import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import type { ObservabilitySummary as Summary } from '@/features/platform-api/types';
import { stepTypeLabel } from '@/features/workflows/step-display';

function seconds(value: number): string {
  if (value < 60) return `${value.toFixed(1)} 秒`;
  return `${(value / 60).toFixed(1)} 分钟`;
}

interface ObservabilitySummaryProps {
  summary: Summary;
}

export function ObservabilitySummary({ summary }: ObservabilitySummaryProps): React.JSX.Element {
  const metrics = [
    ['任务数', String(summary.run_count)],
    ['失败率', `${(summary.failure_rate * 100).toFixed(1)}%`],
    ['平均排队', seconds(summary.average_queue_seconds)],
    ['平均执行', seconds(summary.average_run_seconds)],
    ['重试次数', String(summary.retry_count)],
    ['人工介入', String(summary.manual_intervention_count)]
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>运行观测</CardTitle>
        <CardDescription>
          最近 {summary.window_hours} 小时的脱敏聚合数据，不包含任务原文、凭据或文件路径。
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-5'>
        <PaginatedCollection
          ariaLabel='运行指标'
          contentClassName='grid gap-3 sm:grid-cols-2 lg:grid-cols-6'
        >
          {metrics.map(([label, value]) => (
            <div key={label} className='rounded-lg border p-3'>
              <p className='text-sm text-muted-foreground'>{label}</p>
              <p className='mt-1 text-xl font-semibold'>{value}</p>
            </div>
          ))}
        </PaginatedCollection>
        <div className='grid gap-4 lg:grid-cols-2'>
          <div>
            <h3 className='mb-2 font-medium'>步骤指标</h3>
            {(summary.step_metrics ?? []).length ? (
              <PaginatedCollection
                ariaLabel='步骤指标'
                contentClassName='space-y-2 text-sm'
              >
                {(summary.step_metrics ?? []).map((item) => (
                  <div
                    key={item.step_type}
                    className='flex flex-wrap justify-between gap-2 rounded-lg border p-2'
                  >
                    <span>{stepTypeLabel(item.step_type)}</span>
                    <span className='text-muted-foreground'>
                      {item.run_count} 次 · 失败 {item.failed_count} 次 · 平均{' '}
                      {seconds(item.average_duration_seconds)}
                    </span>
                  </div>
                ))}
              </PaginatedCollection>
            ) : (
              <p className='text-sm text-muted-foreground'>当前时段没有步骤数据。</p>
            )}
          </div>
          <div>
            <h3 className='mb-2 font-medium'>模型调用</h3>
            {(summary.model_usage ?? []).length ? (
              <PaginatedCollection
                ariaLabel='模型调用'
                contentClassName='space-y-2 text-sm'
              >
                {(summary.model_usage ?? []).map((item) => (
                  <div
                    key={`${item.provider}-${item.model}`}
                    className='flex flex-wrap justify-between gap-2 rounded-lg border p-2'
                  >
                    <span>
                      {item.provider} / {item.model}
                    </span>
                    <span className='text-right text-muted-foreground'>
                      {item.request_count} 次 · 失败 {item.failed_count} · 回退{' '}
                      {item.fallback_count}
                      <br />
                      平均 {(item.average_duration_ms / 1000).toFixed(2)} 秒 · Token{' '}
                      {item.input_tokens}/{item.output_tokens}
                    </span>
                  </div>
                ))}
              </PaginatedCollection>
            ) : (
              <p className='text-sm text-muted-foreground'>当前时段没有模型调用记录。</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
