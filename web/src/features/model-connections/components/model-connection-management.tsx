'use client';

import * as React from 'react';
import Link from 'next/link';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PaginatedCollection } from '@/components/ui/collection-pagination';
import { Input } from '@/components/ui/input';
import { Icons } from '@/components/icons';
import type { ModelConnection, ModelProvider } from '@/features/platform-api/types';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';

interface ModelConnectionManagementProps {
  initialConnections: ModelConnection[];
  providers: ModelProvider[];
}

function responseMessage(response: Response, fallback: string): Promise<string> {
  return response
    .json()
    .then((body: unknown) => {
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        return body.detail;
      }
      return fallback;
    })
    .catch(() => fallback);
}

function discoveryLabel(mode: string): string {
  if (mode === 'api') return '自动发现模型';
  if (mode === 'hybrid') return '自动发现或手动填写';
  return '手动填写模型';
}

function connectionStatus(connection: ModelConnection): {
  label: string;
  variant: 'default' | 'destructive';
} {
  return connection.status === 'connected'
    ? { label: '连接正常', variant: 'default' }
    : { label: '连接异常', variant: 'destructive' };
}

export function ModelConnectionManagement({
  initialConnections,
  providers
}: ModelConnectionManagementProps): React.JSX.Element {
  const [connections, setConnections] = React.useState(initialConnections);
  const [providerId, setProviderId] = React.useState(providers[0]?.id ?? '');
  const [apiKey, setApiKey] = React.useState('');
  const [baseUrl, setBaseUrl] = React.useState('');
  const [manualModel, setManualModel] = React.useState('');
  const [modelDrafts, setModelDrafts] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(initialConnections.map((item) => [item.id, item.selected_model]))
  );
  const [creating, setCreating] = React.useState(false);
  const [busyConnectionId, setBusyConnectionId] = React.useState('');
  const [deleteTarget, setDeleteTarget] = React.useState<ModelConnection | null>(null);
  const [message, setMessage] = React.useState('');
  const [error, setError] = React.useState('');
  const selectedProvider = providers.find((item) => item.id === providerId);
  const isCustomProvider = selectedProvider?.id === 'custom_openai';
  const showManualModel = selectedProvider?.allow_manual_model ?? false;

  function replaceConnection(updated: ModelConnection) {
    setConnections((current) => {
      const found = current.some((item) => item.id === updated.id);
      return found
        ? current.map((item) => (item.id === updated.id ? updated : item))
        : [updated, ...current];
    });
    setModelDrafts((current) => ({ ...current, [updated.id]: updated.selected_model }));
  }

  async function createConnection(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!providerId || !apiKey.trim() || creating) return;
    setCreating(true);
    setMessage('');
    setError('');
    try {
      const response = await fetch('/api/platform/admin/model-connections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_id: providerId,
          api_key: apiKey,
          base_url: baseUrl,
          model: manualModel
        })
      });
      if (!response.ok) throw new Error(await responseMessage(response, '模型连接保存失败。'));
      const updated = (await response.json()) as ModelConnection;
      replaceConnection(updated);
      setApiKey('');
      setBaseUrl('');
      setManualModel('');
      setMessage(`${updated.provider_name}连接已验证并保存。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '模型连接保存失败。');
    } finally {
      setCreating(false);
    }
  }

  async function refreshConnection(connection: ModelConnection) {
    if (busyConnectionId) return;
    setBusyConnectionId(connection.id);
    setMessage('');
    setError('');
    try {
      const response = await fetch(
        `/api/platform/admin/model-connections/${encodeURIComponent(connection.id)}/refresh`,
        { method: 'POST' }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '模型连接验证失败。'));
      const updated = (await response.json()) as ModelConnection;
      replaceConnection(updated);
      setMessage(`${updated.provider_name}连接验证成功，可用模型列表已更新。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '模型连接验证失败。');
    } finally {
      setBusyConnectionId('');
    }
  }

  async function saveSelectedModel(connection: ModelConnection) {
    const selectedModel = modelDrafts[connection.id] ?? '';
    if (!selectedModel || busyConnectionId) return;
    setBusyConnectionId(connection.id);
    setMessage('');
    setError('');
    try {
      const response = await fetch(
        `/api/platform/admin/model-connections/${encodeURIComponent(connection.id)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ selected_model: selectedModel })
        }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '默认模型保存失败。'));
      const updated = (await response.json()) as ModelConnection;
      replaceConnection(updated);
      setMessage(`${updated.provider_name}的连接默认模型已保存。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '默认模型保存失败。');
    } finally {
      setBusyConnectionId('');
    }
  }

  async function deleteConnection() {
    if (!deleteTarget || busyConnectionId) return;
    const target = deleteTarget;
    setBusyConnectionId(target.id);
    setMessage('');
    setError('');
    try {
      const response = await fetch(
        `/api/platform/admin/model-connections/${encodeURIComponent(target.id)}`,
        { method: 'DELETE' }
      );
      if (!response.ok) throw new Error(await responseMessage(response, '模型连接删除失败。'));
      setConnections((current) => current.filter((item) => item.id !== target.id));
      setModelDrafts((current) => {
        const next = { ...current };
        delete next[target.id];
        return next;
      });
      setDeleteTarget(null);
      setMessage(`${target.provider_name}连接已删除。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '模型连接删除失败。');
    } finally {
      setBusyConnectionId('');
    }
  }

  return (
    <div className='space-y-4'>
      <Card>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Icons.lock className='size-5' /> 新增模型连接
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className='grid gap-4 lg:grid-cols-2'
            onSubmit={(event) => void createConnection(event)}
          >
            <label htmlFor='model-provider' className='grid gap-1.5 text-sm font-medium'>
              模型供应商
              <select
                id='model-provider'
                className='h-11 rounded-md border bg-background px-3 font-normal'
                value={providerId}
                required
                disabled={creating}
                onChange={(event) => {
                  setProviderId(event.target.value);
                  setBaseUrl('');
                  setManualModel('');
                }}
              >
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
              {selectedProvider ? (
                <span className='text-xs font-normal text-muted-foreground'>
                  {discoveryLabel(selectedProvider.discovery_mode)}
                </span>
              ) : null}
            </label>

            <label htmlFor='model-api-key' className='grid gap-1.5 text-sm font-medium'>
              API Key
              <Input
                id='model-api-key'
                className='h-11'
                type='password'
                value={apiKey}
                minLength={8}
                maxLength={512}
                required
                autoComplete='new-password'
                spellCheck={false}
                disabled={creating}
                onChange={(event) => setApiKey(event.target.value)}
              />
              <span className='text-xs font-normal text-muted-foreground'>
                保存后无法从平台读取原始值；更换密钥时重新提交连接。
              </span>
            </label>

            {isCustomProvider ? (
              <label htmlFor='model-base-url' className='grid gap-1.5 text-sm font-medium'>
                服务地址
                <Input
                  id='model-base-url'
                  className='h-11'
                  type='url'
                  value={baseUrl}
                  maxLength={512}
                  required
                  placeholder='https://example.com/v1'
                  disabled={creating}
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
                <span className='text-xs font-normal text-muted-foreground'>
                  仅支持管理员允许访问的 HTTPS OpenAI 兼容服务。
                </span>
              </label>
            ) : null}

            {showManualModel ? (
              <label htmlFor='manual-model-name' className='grid gap-1.5 text-sm font-medium'>
                模型名称{isCustomProvider ? '' : '（可选）'}
                <Input
                  id='manual-model-name'
                  className='h-11'
                  value={manualModel}
                  maxLength={255}
                  required={isCustomProvider}
                  placeholder={
                    isCustomProvider ? '输入服务提供的文本模型名称' : '自动发现失败时填写'
                  }
                  disabled={creating}
                  onChange={(event) => setManualModel(event.target.value)}
                />
              </label>
            ) : null}

            <div className='flex items-end lg:col-span-2'>
              <Button
                type='submit'
                className='min-h-11 w-full sm:w-auto'
                disabled={!providerId || apiKey.trim().length < 8 || creating}
              >
                {creating ? (
                  <Icons.spinner className='size-4 animate-spin' />
                ) : (
                  <Icons.check className='size-4' />
                )}
                {creating ? '正在验证并保存…' : '验证并保存连接'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className='gap-3 sm:flex-row sm:items-start sm:justify-between'>
          <div>
            <CardTitle>已保存的模型连接</CardTitle>
          </div>
          <Link
            href='/dashboard/ai-chat'
            className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'min-h-11')}
          >
            配置 AI 助手默认模型
          </Link>
        </CardHeader>
        <CardContent className='space-y-3'>
          {connections.length ? (
            <PaginatedCollection ariaLabel='模型连接' contentClassName='space-y-3'>
              {connections.map((connection) => {
              const status = connectionStatus(connection);
              const busy = busyConnectionId === connection.id;
              const selectedModel = modelDrafts[connection.id] ?? connection.selected_model;
              return (
                <div
                  key={connection.id}
                  className='grid gap-4 rounded-lg border p-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,26rem)]'
                >
                  <div className='min-w-0 space-y-2'>
                    <div className='flex flex-wrap items-center gap-2'>
                      <p className='font-medium'>{connection.provider_name}</p>
                      <Badge variant={status.variant}>{status.label}</Badge>
                    </div>
                    <p className='text-sm text-muted-foreground'>密钥：{connection.api_key_hint}</p>
                    <p className='text-sm text-muted-foreground'>
                      当前连接默认模型：{connection.selected_model}
                    </p>
                    <p className='text-xs text-muted-foreground'>
                      最近验证：
                      {formatDate(connection.last_checked_at, {
                        hour: '2-digit',
                        minute: '2-digit'
                      })}
                    </p>
                  </div>
                  <div className='grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end'>
                    <label
                      htmlFor={`connection-model-${connection.id}`}
                      className='grid gap-1.5 text-sm font-medium'
                    >
                      连接默认模型
                      <select
                        id={`connection-model-${connection.id}`}
                        className='h-11 min-w-0 rounded-md border bg-background px-3 font-normal'
                        value={selectedModel}
                        disabled={busy || connection.models.length === 0}
                        onChange={(event) =>
                          setModelDrafts((current) => ({
                            ...current,
                            [connection.id]: event.target.value
                          }))
                        }
                      >
                        {connection.models.map((model) => (
                          <option key={model} value={model}>
                            {model}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className='flex flex-wrap gap-2'>
                      <Button
                        type='button'
                        variant='outline'
                        className='min-h-11'
                        disabled={
                          Boolean(busyConnectionId) || selectedModel === connection.selected_model
                        }
                        onClick={() => void saveSelectedModel(connection)}
                      >
                        保存模型
                      </Button>
                      <Button
                        type='button'
                        variant='outline'
                        className='min-h-11'
                        disabled={Boolean(busyConnectionId)}
                        onClick={() => void refreshConnection(connection)}
                      >
                        {busy ? <Icons.spinner className='size-4 animate-spin' /> : null}
                        重新验证
                      </Button>
                      <Button
                        type='button'
                        variant='destructive'
                        className='min-h-11'
                        disabled={Boolean(busyConnectionId)}
                        onClick={() => setDeleteTarget(connection)}
                      >
                        <Icons.trash className='size-4' /> 删除
                      </Button>
                    </div>
                  </div>
                </div>
              );
              })}
            </PaginatedCollection>
          ) : (
            <div className='rounded-lg border border-dashed p-6 text-center'>
              <p className='font-medium'>还没有模型连接</p>
            </div>
          )}
          <div aria-live='polite'>
            {message ? (
              <p className='text-sm text-emerald-700 dark:text-emerald-400'>{message}</p>
            ) : null}
            {error ? (
              <p role='alert' className='text-sm text-destructive'>
                {error}
              </p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <AlertDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除模型连接</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除{deleteTarget ? `“${deleteTarget.provider_name}”` : ''}连接吗？如果 AI
              助手正在使用该连接，平台会阻止删除并提示先更换配置。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(busyConnectionId)}>取消</AlertDialogCancel>
            <AlertDialogAction
              variant='destructive'
              disabled={Boolean(busyConnectionId)}
              onClick={() => void deleteConnection()}
            >
              {busyConnectionId ? '删除中…' : '确认删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
