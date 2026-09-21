import { submitDraftRequest } from '@/features/run-setup/draft-submission';
import { platformApiError } from '@/features/platform-api/errors';
import type {
  ConfirmedRun,
  ConfirmTaskDraftInput,
  CreateRunInput,
  CreatedRun,
  UploadedSkillFile,
  UploadSkillFileInput
} from './types';

async function responseError(response: Response, fallback: string): Promise<Error> {
  let body: unknown = null;
  try { body = await response.json(); } catch { /* Bounded fallback for non-JSON errors. */ }
  return platformApiError(response.status, body, fallback);
}

export async function uploadSkillFile(input: UploadSkillFileInput): Promise<UploadedSkillFile> {
  const form = new FormData();
  form.set('skill_id', input.skillId);
  form.set('role', input.role);
  form.set('upload', input.file);
  const response = await fetch('/api/platform/files', { method: 'POST', body: form });
  if (!response.ok) throw await responseError(response, '文件上传失败。');
  return (await response.json()) as UploadedSkillFile;
}

export async function deleteSkillFile(fileId: string): Promise<void> {
  const response = await fetch(`/api/platform/files/${encodeURIComponent(fileId)}`, {
    method: 'DELETE'
  });
  if (!response.ok) throw await responseError(response, '文件删除失败。');
}

export async function createRun(input: CreateRunInput): Promise<CreatedRun> {
  const response = await fetch('/api/platform/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input)
  });
  if (!response.ok) throw await responseError(response, '任务创建失败。');
  return (await response.json()) as CreatedRun;
}

export async function confirmRun(runId: string): Promise<ConfirmedRun> {
  const response = await fetch(`/api/platform/runs/${encodeURIComponent(runId)}/confirm`, {
    method: 'POST'
  });
  if (!response.ok) throw await responseError(response, '任务确认失败。');
  return (await response.json()) as ConfirmedRun;
}

export async function confirmTaskDraft(input: ConfirmTaskDraftInput): Promise<CreatedRun> {
  const response = await submitDraftRequest(input);
  if (!response.ok) throw await responseError(response, '任务草稿提交失败。');
  return (await response.json()) as CreatedRun;
}
