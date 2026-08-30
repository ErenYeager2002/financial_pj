'use client';

import * as React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import type { FeatureControl } from '@/features/platform-api/types';
import { cn } from '@/lib/utils';

const categoryNames: Record<FeatureControl['category'], string> = {
  automation: '自动化',
  execution: '任务执行',
  authentication: '登录认证'
};

export function FeatureControlList({ initialControls }: { initialControls: FeatureControl[] }) {
  const [controls, setControls] = React.useState(initialControls);
  const [savingKey, setSavingKey] = React.useState('');
  const [message, setMessage] = React.useState('');
  const [error, setError] = React.useState('');

  async function change(control: FeatureControl, enabled: boolean) {
    if (!control.editable) return;
    if (!enabled && !window.confirm(`确认关闭${control.name}吗？`)) return;
    setSavingKey(control.key);
    setMessage('');
    setError('');
    try {
      const response = await fetch(
        `/api/platform/admin/feature-controls/${encodeURIComponent(control.key)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled })
        }
      );
      const body = (await response.json()) as FeatureControl | { detail?: string };
      if (!response.ok) {
        throw new Error('detail' in body && body.detail ? body.detail : '功能开关保存失败。');
      }
      const updated = body as FeatureControl;
      setControls((current) => current.map((item) => (item.key === updated.key ? updated : item)));
      setMessage(`${updated.name}已${updated.enabled ? '开启' : '关闭'}，后台下一次轮询生效。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '功能开关保存失败。');
    } finally {
      setSavingKey('');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>功能开关</CardTitle>
        <CardDescription>可在线修改的开关立即生效；部署级配置不可在线修改。</CardDescription>
      </CardHeader>
      <CardContent>
        <div className='divide-y rounded-lg border'>
          {controls.map((control) => {
            const saving = savingKey === control.key;
            return (
              <div
                key={control.key}
                className='grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center'
              >
                <div className='min-w-0 space-y-1'>
                  <div className='flex flex-wrap items-center gap-2'>
                    <p className='font-medium'>{control.name}</p>
                    <span className='rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground'>
                      {categoryNames[control.category]}
                    </span>
                    <span
                      className={cn(
                        'rounded-md px-2 py-0.5 text-xs font-medium',
                        control.enabled
                          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                          : 'bg-muted text-muted-foreground'
                      )}
                    >
                      {control.enabled ? '已开启' : '已关闭'}
                    </span>
                  </div>
                  <p className='text-sm text-muted-foreground'>{control.description}</p>
                  <p className='text-xs text-muted-foreground'>
                    {control.editable ? '管理员可在线修改' : control.blocked_reason}
                  </p>
                </div>
                <div className='flex items-center gap-3 md:justify-end'>
                  <span className='text-xs text-muted-foreground'>
                    {control.source === 'administrator' ? '管理员设置' : '部署配置'}
                  </span>
                  <Switch
                    aria-label={`${control.enabled ? '关闭' : '开启'}${control.name}`}
                    checked={control.enabled}
                    disabled={!control.editable || Boolean(savingKey)}
                    onCheckedChange={(checked) => void change(control, checked)}
                  />
                  <span className='w-12 text-sm'>{saving ? '保存中' : ''}</span>
                </div>
              </div>
            );
          })}
        </div>
        {message ? (
          <p className='mt-3 text-sm text-emerald-700 dark:text-emerald-400'>{message}</p>
        ) : null}
        {error ? (
          <p role='alert' className='mt-3 text-sm text-destructive'>
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
