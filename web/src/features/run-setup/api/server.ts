import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  PlatformFile,
  RunActionResponse,
  RunCreate,
  RunDetail,
  SkillDetail
} from '@/features/platform-api/types';
import { getSkillCatalogItem } from '@/features/skills/api/server';
import { isRunnableSkill } from '@/features/run-setup/run-eligibility';

const ID = /^[A-Za-z0-9._-]+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

function checkedId(value: string, label: string, pattern = ID): string {
  if (!pattern.test(value)) throw new PlatformApiError(400, `${label}格式无效。`);
  return value;
}

function safeSkill(skill: SkillDetail): SkillDetail {
  if (!isRunnableSkill(skill)) {
    throw new PlatformApiError(403, '该 Skill 不能通过标准只读任务入口执行。');
  }
  return skill;
}

function uploadableSkill(skill: SkillDetail, allowWorkflow: boolean): SkillDetail {
  if (allowWorkflow && skill.execution_mode === 'guided_workflow') return skill;
  return safeSkill(skill);
}

function fileExtension(name: string): string {
  const index = name.lastIndexOf('.');
  return index < 0 ? '' : name.slice(index + 1).toLowerCase();
}

export async function uploadFileForSkill(
  skillId: string,
  role: string,
  upload: File,
  allowWorkflow = false
): Promise<PlatformFile> {
  checkedId(skillId, 'Skill 标识');
  checkedId(role, '文件用途');
  if (!upload.name || upload.size <= 0) throw new PlatformApiError(400, '请选择非空文件。');
  if (upload.size > MAX_UPLOAD_BYTES) throw new PlatformApiError(413, '文件不能超过 100 MB。');

  const skill = uploadableSkill(await getSkillCatalogItem(skillId), allowWorkflow);
  const spec = skill.file_inputs?.find((item) => item.role === role);
  if (!spec) throw new PlatformApiError(400, '该 Skill 不接受此文件用途。');
  const extension = fileExtension(upload.name);
  if (
    spec.extensions?.length &&
    !spec.extensions.some((item) => item.toLowerCase() === extension)
  ) {
    throw new PlatformApiError(415, `文件格式不支持，请上传 ${spec.extensions.join('、')} 文件。`);
  }
  const maxBytes = (spec.max_size_mb ?? 100) * 1024 * 1024;
  if (upload.size > maxBytes) {
    throw new PlatformApiError(413, `文件不能超过 ${spec.max_size_mb ?? 100} MB。`);
  }

  const form = new FormData();
  form.set('skill_id', skillId);
  form.set('role', role);
  form.set('upload', upload);
  return platformServerRequest<PlatformFile>('/api/files', { method: 'POST', body: form });
}

export function deleteUploadedFile(fileId: string): Promise<null> {
  return platformServerRequest<null>(`/api/files/${checkedId(fileId, '文件标识', UUID)}`, {
    method: 'DELETE'
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function checkedRunCreate(value: unknown): RunCreate {
  if (!isRecord(value)) throw new PlatformApiError(400, '任务参数格式无效。');
  const allowed = new Set(['skill_id', 'message', 'parameters', 'files', 'idempotency_key']);
  if (Object.keys(value).some((key) => !allowed.has(key))) {
    throw new PlatformApiError(400, '任务参数包含不允许的字段。');
  }
  if (typeof value.skill_id !== 'string') throw new PlatformApiError(400, 'Skill 标识不能为空。');
  const skillId = checkedId(value.skill_id, 'Skill 标识');
  if (typeof value.idempotency_key !== 'string') {
    throw new PlatformApiError(400, '任务幂等标识不能为空。');
  }
  const idempotencyKey = checkedId(value.idempotency_key, '任务幂等标识', UUID);
  const message = typeof value.message === 'string' ? value.message : '';
  if (message.length > 4000) throw new PlatformApiError(400, '任务说明不能超过 4000 字。');
  if (!isRecord(value.parameters)) throw new PlatformApiError(400, '任务参数格式无效。');
  if (!isRecord(value.files)) throw new PlatformApiError(400, '任务文件格式无效。');
  const files: Record<string, string | string[]> = {};
  for (const [role, fileValue] of Object.entries(value.files)) {
    checkedId(role, '文件用途');
    if (typeof fileValue === 'string') {
      files[role] = checkedId(fileValue, '文件标识', UUID);
      continue;
    }
    const consolidationReports = skillId === 'consolidated-statements' && role === 'reports';
    const maximumFiles = consolidationReports ? 24 : 20;
    const minimumFiles = consolidationReports && value.parameters.fetch_kingdee === true ? 0 : 1;
    if (!Array.isArray(fileValue) || fileValue.length < minimumFiles || fileValue.length > maximumFiles) {
      throw new PlatformApiError(400, `每个文件用途必须包含 ${minimumFiles} 到 ${maximumFiles} 个文件。`);
    }
    files[role] = fileValue.map((item) => {
      if (typeof item !== 'string') throw new PlatformApiError(400, '文件标识格式无效。');
      return checkedId(item, '文件标识', UUID);
    });
  }
  return {
    skill_id: skillId,
    message,
    parameters: value.parameters,
    files,
    idempotency_key: idempotencyKey
  };
}

export async function createSafeRun(value: unknown): Promise<RunDetail> {
  const body = checkedRunCreate(value);
  safeSkill(await getSkillCatalogItem(body.skill_id));
  return platformServerRequest<RunDetail>('/api/runs', {
    method: 'POST',
    body: JSON.stringify(body)
  });
}

export function confirmCreatedRun(runId: string): Promise<RunActionResponse> {
  return platformServerRequest<RunActionResponse>(
    `/api/runs/${checkedId(runId, '任务标识', UUID)}/confirm`,
    { method: 'POST' }
  );
}
