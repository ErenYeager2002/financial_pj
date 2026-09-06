'use client';

import { useEffect, useMemo, useState } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import type { AdminAssistantProfile, ModelConnection } from '@/features/platform-api/types';

interface AssistantModelSelectorProps {
  isAdmin: boolean;
  initialModel: string;
  profile?: AdminAssistantProfile;
  connections: ModelConnection[];
  onSave: (connectionId: string, model: string) => Promise<AdminAssistantProfile>;
}

export function AssistantModelSelector({
  isAdmin,
  initialModel,
  profile,
  connections,
  onSave
}: AssistantModelSelectorProps) {
  const savedProfileConnectionId = profile?.connection_id ?? '';
  const savedProfileModel = profile?.model ?? '';
  const firstConnectedConnection = connections.find((item) => item.status === 'connected');
  const initialDraftConnectionId = savedProfileConnectionId || firstConnectedConnection?.id || '';
  const initialDraftConnection = connections.find(
    (item) => item.id === initialDraftConnectionId
  );
  const initialDraftModel =
    savedProfileModel ||
    initialDraftConnection?.selected_model ||
    initialDraftConnection?.models[0] ||
    '';
  const [savedConnectionId, setSavedConnectionId] = useState(savedProfileConnectionId);
  const [savedModel, setSavedModel] = useState(savedProfileModel);
  const [draftConnectionId, setDraftConnectionId] = useState(initialDraftConnectionId);
  const [draftModel, setDraftModel] = useState(initialDraftModel);
  const [modelSearch, setModelSearch] = useState('');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const visibleSavedModel = isAdmin ? savedModel : initialModel;

  useEffect(() => {
    const nextSavedConnectionId = profile?.connection_id ?? '';
    const nextSavedModel = profile?.model ?? '';
    const nextDraftConnectionId =
      nextSavedConnectionId || connections.find((item) => item.status === 'connected')?.id || '';
    const nextDraftConnection = connections.find((item) => item.id === nextDraftConnectionId);
    const nextDraftModel =
      nextSavedModel ||
      nextDraftConnection?.selected_model ||
      nextDraftConnection?.models[0] ||
      '';
    setSavedConnectionId(nextSavedConnectionId);
    setSavedModel(nextSavedModel);
    setDraftConnectionId(nextDraftConnectionId);
    setDraftModel(nextDraftModel);
  }, [connections, profile?.connection_id, profile?.model]);

  const selectedConnection = connections.find((item) => item.id === draftConnectionId);
  const filteredModels = useMemo(() => {
    const query = modelSearch.trim().toLowerCase();
    return (selectedConnection?.models ?? []).filter(
      (model) => !query || model.toLowerCase().includes(query)
    );
  }, [modelSearch, selectedConnection]);

  if (!isAdmin) {
    return (
      <span className='rounded-md border px-2.5 py-1.5 text-sm' aria-label='当前助手模型'>
        {visibleSavedModel || '尚未配置'}
      </span>
    );
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      const nextConnectionId =
        savedConnectionId || connections.find((item) => item.status === 'connected')?.id || '';
      const nextConnection = connections.find((item) => item.id === nextConnectionId);
      const nextModel =
        savedModel || nextConnection?.selected_model || nextConnection?.models[0] || '';
      setDraftConnectionId(nextConnectionId);
      setDraftModel(nextModel);
      setModelSearch('');
      setMessage('');
    }
    setOpen(nextOpen);
  }

  function changeConnection(connectionId: string) {
    const connection = connections.find((item) => item.id === connectionId);
    setDraftConnectionId(connectionId);
    setDraftModel(connection?.selected_model || connection?.models[0] || '');
  }

  async function save() {
    if (!selectedConnection || selectedConnection.status !== 'connected' || !draftModel) return;
    setBusy(true);
    setMessage('');
    try {
      const saved = await onSave(draftConnectionId, draftModel);
      setSavedConnectionId(saved.connection_id);
      setSavedModel(saved.model);
      setDraftConnectionId(saved.connection_id);
      setDraftModel(saved.model);
      setMessage('默认模型已保存。');
      setOpen(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '配置保存失败。');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogTrigger
          render={
            <Button
              type='button'
              variant='outline'
              size='sm'
              aria-label='选择助手默认模型'
              aria-haspopup='dialog'
            />
          }
        >
          <span className='max-w-44 truncate'>{savedModel || '选择模型'}</span>
          <Icons.chevronDown className='size-4' aria-hidden='true' />
        </DialogTrigger>
        <DialogContent className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg'>
          <DialogHeader>
            <DialogTitle>设置助手默认模型</DialogTitle>
            <DialogDescription>
              临时切换不会保存；明确点击设为助手默认模型后，部门默认配置才会更新。
            </DialogDescription>
          </DialogHeader>
          {connections.length ? (
            <div className='space-y-4'>
              <label className='grid gap-1.5 text-sm font-medium'>
                模型连接
                <select
                  className='h-9 rounded-md border bg-background px-3 font-normal'
                  value={draftConnectionId}
                  onChange={(event) => changeConnection(event.target.value)}
                >
                  <option value='' disabled>
                    请选择模型连接
                  </option>
                  {connections.map((connection) => (
                    <option
                      key={connection.id}
                      value={connection.id}
                      disabled={connection.status !== 'connected'}
                    >
                      {connection.provider_name} · {connection.api_key_hint}
                      {connection.status !== 'connected' ? '（不可用）' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label className='grid gap-1.5 text-sm font-medium'>
                搜索模型
                <Input
                  value={modelSearch}
                  onChange={(event) => setModelSearch(event.target.value)}
                  placeholder='输入模型名称'
                  aria-label='搜索模型'
                />
              </label>
              <label className='grid gap-1.5 text-sm font-medium'>
                模型
                <select
                  className='max-h-48 min-h-9 rounded-md border bg-background px-3 font-normal'
                  value={draftModel}
                  onChange={(event) => setDraftModel(event.target.value)}
                  disabled={!selectedConnection || selectedConnection.status !== 'connected'}
                >
                  <option value='' disabled>
                    请选择模型
                  </option>
                  {filteredModels.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </label>
              {message && (
                <p role='alert' className='text-sm text-destructive'>
                  {message}
                </p>
              )}
            </div>
          ) : (
            <p className='text-sm text-muted-foreground'>暂无已保存的模型连接。</p>
          )}
          <DialogFooter>
            <Button type='button' variant='outline' onClick={() => setOpen(false)} disabled={busy}>
              取消
            </Button>
            <Button
              type='button'
              onClick={() => void save()}
              disabled={
                busy ||
                !selectedConnection ||
                selectedConnection.status !== 'connected' ||
                !draftModel
              }
            >
              {busy && <Icons.spinner className='size-4 animate-spin' />}
              设为助手默认模型
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
