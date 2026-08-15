import type {
  ConfirmedRun,
  ConfirmTaskDraftInput,
  CreateRunInput,
  CreatedRun,
  UploadedSkillFile,
  UploadSkillFileInput
} from './types';

async function responseError(response: Response, fallback: string): Promise<Error> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return new Error(fallback);
  }
  if (
    typeof body === 'object' &&
    body !== null &&
    'detail' in body &&
    typeof body.detail === 'string'
  ) {
    return new Error(body.detail);
  }
  return new Error(fallback);
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
  const draftId = encodeURIComponent(input.draftId);
  const update = await fetch(`/api/platform/task-drafts/${draftId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parameters: input.parameters, files: input.files })
  });
  if (!update.ok) throw await responseError(update, '任务草稿更新失败。');
  const response = await fetch(`/api/platform/task-drafts/${draftId}/confirm`, {
    method: 'POST'
  });
  if (!response.ok) throw await responseError(response, '任务草稿确认失败。');
  return (await response.json()) as CreatedRun;
}
