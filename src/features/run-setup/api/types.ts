import type {
  PlatformFile,
  RunActionResponse,
  RunCreate,
  RunDetail
} from '@/features/platform-api/types';

export type UploadedSkillFile = PlatformFile;
export type CreatedRun = RunDetail;
export type ConfirmedRun = RunActionResponse;

export interface UploadSkillFileInput {
  skillId: string;
  role: string;
  file: File;
}

export interface CreateRunInput {
  skill_id: string;
  message: string;
  parameters: Record<string, unknown>;
  files: Record<string, string | string[]>;
  idempotency_key: string;
}

export interface ConfirmTaskDraftInput {
  draftId: string;
  parameters: Record<string, unknown>;
  files: Record<string, string | string[]>;
}

export type RunCreatePayload = Pick<
  RunCreate,
  'skill_id' | 'message' | 'parameters' | 'files' | 'idempotency_key'
>;
