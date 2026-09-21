'use client';

import {useState} from 'react';
import {AssistantModelSelector} from './assistant-model-selector';
import {platformClientRequest} from '@/features/platform-api/client';
import type {AdminAssistantProfile, AssistantStatus, ModelConnection} from '@/features/platform-api/types';

type Props = {
  isAdmin: boolean;
  status: AssistantStatus;
  profile?: AdminAssistantProfile;
  connections: ModelConnection[];
};

export function AssistantDefaultModel({isAdmin, status, profile, connections}: Props) {
  const [savedProfile, setSavedProfile] = useState(profile);
  async function save(connectionId: string, model: string): Promise<AdminAssistantProfile> {
    const saved = await platformClientRequest<AdminAssistantProfile>('/api/platform/admin/assistant-profile', '默认模型保存失败。', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({connection_id: connectionId, model})
    });
    setSavedProfile(saved);
    return saved;
  }
  return <div className='flex flex-wrap items-center gap-2' aria-label='助手默认模型设置'>
    <span className='text-sm text-muted-foreground'>助手默认模型</span>
    <AssistantModelSelector isAdmin={isAdmin} initialModel={status.model}
      profile={savedProfile} connections={connections} onSave={save}/>
  </div>;
}
