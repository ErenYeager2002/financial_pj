'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import type {
  AdminUser,
  ServiceCredentialRead,
  TaskReminderSubscription
} from '@/features/platform-api/types';

export function TaskReminderAssignment({
  users,
  initialSubscription,
  initialCredential
}: {
  users: AdminUser[];
  initialSubscription: TaskReminderSubscription | null;
  initialCredential: ServiceCredentialRead | null;
}) {
  const activeUsers = users.filter((user) => user.status === 'active');
  const [ownerId, setOwnerId] = React.useState(initialSubscription?.owner_id ?? '');
  const [enabled, setEnabled] = React.useState(initialSubscription?.enabled ?? true);
  const [subscription, setSubscription] = React.useState<TaskReminderSubscription | null>(
    initialSubscription
  );
  const [credential, setCredential] = React.useState<ServiceCredentialRead | null>(
    initialCredential
  );
  const [account, setAccount] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [checkStart, setCheckStart] = React.useState('');
  const [checkEnd, setCheckEnd] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState('');

  async function save() {
    setSaving(true);
    setMessage('');
    try {
      const response = await fetch(
        '/api/platform/admin/task-reminder-subscriptions/ar-hexiao-daily',
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ owner_id: ownerId, enabled })
        }
      );
      const body = (await response.json()) as TaskReminderSubscription | { detail?: string };
      if (!response.ok) {
        throw new Error('detail' in body && body.detail ? body.detail : '负责人保存失败。');
      }
      setSubscription(body as TaskReminderSubscription);
      const statusResponse = await fetch(
        '/api/platform/admin/task-reminder-subscriptions/ar-hexiao-daily/credential'
      );
      if (statusResponse.ok) {
        setCredential((await statusResponse.json()) as ServiceCredentialRead);
      }
      setMessage('已保存，系统已排入一次只读检查。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '负责人保存失败。');
    } finally {
      setSaving(false);
    }
  }

  async function saveCredential() {
    setSaving(true);
    setMessage('');
    try {
      const response = await fetch(
        '/api/platform/admin/task-reminder-subscriptions/ar-hexiao-daily/credential',
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account, password })
        }
      );
      const body = (await response.json()) as ServiceCredentialRead | { detail?: string };
      if (!response.ok) {
        throw new Error('detail' in body && body.detail ? body.detail : '凭据保存失败。');
      }
      setCredential(body as ServiceCredentialRead);
      setAccount('');
      setPassword('');
      setMessage('负责人凭据已加密保存，页面不会显示明文。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '凭据保存失败。');
    } finally {
      setSaving(false);
    }
  }

  async function deleteCredential() {
    if (!window.confirm('确认删除当前负责人的智云凭据吗？自动检查会暂停。')) return;
    setSaving(true);
    setMessage('');
    try {
      const response = await fetch(
        '/api/platform/admin/task-reminder-subscriptions/ar-hexiao-daily/credential',
        { method: 'DELETE' }
      );
      if (!response.ok) throw new Error('凭据删除失败。');
      setCredential(null);
      setMessage('负责人凭据已删除，自动检查会提示凭据缺失。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '凭据删除失败。');
    } finally {
      setSaving(false);
    }
  }

  async function testCredential() {
    const target = new Date();
    target.setDate(target.getDate() - 1);
    const businessDate = [
      target.getFullYear(),
      String(target.getMonth() + 1).padStart(2, '0'),
      String(target.getDate()).padStart(2, '0')
    ].join('-');
    setSaving(true);
    setMessage('');
    try {
      const response = await fetch('/api/platform/task-reminders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skill_id: 'ar-hexiao-daily',
          business_dates: [businessDate]
        })
      });
      if (!response.ok) throw new Error('凭据测试排队失败。');
      setMessage(`已排入 ${businessDate} 的只读检查，可在任务中心查看结果。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '凭据测试排队失败。');
    } finally {
      setSaving(false);
    }
  }

  async function checkRange() {
    const start = new Date(`${checkStart}T00:00:00Z`);
    const end = new Date(`${checkEnd}T00:00:00Z`);
    const dates: string[] = [];
    for (let current = start; current <= end && dates.length <= 31; ) {
      dates.push(current.toISOString().slice(0, 10));
      current = new Date(current.getTime() + 24 * 60 * 60 * 1000);
    }
    if (!dates.length || dates.length > 31) {
      setMessage('检查范围必须是最近 31 天内的一段连续日期。');
      return;
    }
    setSaving(true);
    setMessage('');
    try {
      const response = await fetch('/api/platform/task-reminders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skill_id: 'ar-hexiao-daily',
          business_dates: dates
        })
      });
      if (!response.ok) throw new Error('指定日期检查排队失败。');
      setMessage(`已排入 ${checkStart} 至 ${checkEnd} 的只读检查。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '指定日期检查排队失败。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>应收核销任务提醒</CardTitle>
        <CardDescription>
          工作日 09:10 自动检查；只读取回款日期和数量，不创建正式核销任务。
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        <div className='flex flex-wrap items-end gap-3'>
          <label className='grid min-w-64 gap-1 text-sm'>
            <span className='text-muted-foreground'>指定负责人</span>
            <select
              value={ownerId}
              onChange={(event) => setOwnerId(event.target.value)}
              className='h-9 rounded-md border bg-background px-3'
            >
              <option value=''>请选择负责人</option>
              {activeUsers.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name}（{user.username}）
                </option>
              ))}
            </select>
          </label>
          <label className='flex h-9 items-center gap-2 text-sm'>
            <input
              type='checkbox'
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
            />
            启用提醒
          </label>
          <Button disabled={!ownerId || saving} onClick={() => void save()}>
            {saving ? '正在保存' : '保存负责人'}
          </Button>
        </div>
        {subscription ? (
          <p className='text-sm text-muted-foreground'>
            当前负责人：{subscription.owner_name} · 时区 {subscription.timezone} · 每天{' '}
            {subscription.schedule_time}
          </p>
        ) : null}
        {subscription ? (
          <div className='space-y-3 rounded-lg border p-3'>
            <p className='text-sm font-medium'>负责人智云凭据</p>
            <p className='text-sm text-muted-foreground'>
              {credential?.configured
                ? `已配置：${credential.account_hint}`
                : '尚未配置；系统不会显示已保存的账号或密码明文。'}
            </p>
            <div className='grid gap-2 md:grid-cols-2'>
              <Input
                value={account}
                onChange={(event) => setAccount(event.target.value)}
                placeholder='重新填写智云账号'
                autoComplete='off'
              />
              <Input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder='重新填写智云密码'
                type='password'
                autoComplete='new-password'
              />
            </div>
            <div className='flex flex-wrap gap-2'>
              <Button
                size='sm'
                variant='outline'
                disabled={saving || !account || !password}
                onClick={() => void saveCredential()}
              >
                加密保存凭据
              </Button>
              <Button
                size='sm'
                variant='outline'
                disabled={saving || !credential?.configured}
                onClick={() => void testCredential()}
              >
                测试凭据
              </Button>
              <Button
                size='sm'
                variant='destructive'
                disabled={saving || !credential?.configured}
                onClick={() => void deleteCredential()}
              >
                删除凭据
              </Button>
            </div>
          </div>
        ) : null}
        {subscription ? (
          <div className='space-y-3 rounded-lg border p-3'>
            <p className='text-sm font-medium'>手动检查日期范围</p>
            <div className='flex flex-wrap items-end gap-2'>
              <label htmlFor='task-reminder-check-start' className='grid gap-1 text-sm'>
                <span className='text-muted-foreground'>开始日期</span>
                <Input
                  id='task-reminder-check-start'
                  type='date'
                  value={checkStart}
                  onChange={(event) => setCheckStart(event.target.value)}
                />
              </label>
              <label htmlFor='task-reminder-check-end' className='grid gap-1 text-sm'>
                <span className='text-muted-foreground'>结束日期</span>
                <Input
                  id='task-reminder-check-end'
                  type='date'
                  value={checkEnd}
                  onChange={(event) => setCheckEnd(event.target.value)}
                />
              </label>
              <Button
                size='sm'
                variant='outline'
                disabled={saving || !checkStart || !checkEnd}
                onClick={() => void checkRange()}
              >
                检查日期范围
              </Button>
            </div>
          </div>
        ) : null}
        {message ? <p className='text-sm text-muted-foreground'>{message}</p> : null}
      </CardContent>
    </Card>
  );
}
