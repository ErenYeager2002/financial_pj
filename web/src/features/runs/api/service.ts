import { platformClientRequest } from '@/features/platform-api/client';
import type {
  PlatformRunApproval,
  PlatformRunDetail,
  PlatformRunStep,
  RunRetryResult
} from './types';

export async function fetchRun(runId: string): Promise<PlatformRunDetail> {
  return platformClientRequest<PlatformRunDetail>(
    `/api/platform/runs/${encodeURIComponent(runId)}`,
    '任务详情加载失败。'
  );
}

export async function fetchRunSteps(runId: string): Promise<PlatformRunStep[]> {
  return platformClientRequest<PlatformRunStep[]>(
    `/api/platform/runs/${encodeURIComponent(runId)}/steps`,
    '任务步骤加载失败。'
  );
}

export async function fetchRunApprovals(runId: string): Promise<PlatformRunApproval[]> {
  return platformClientRequest<PlatformRunApproval[]>(
    `/api/platform/runs/${encodeURIComponent(runId)}/approvals`,
    '任务审批记录加载失败。'
  );
}

export async function retryRun(runId: string): Promise<RunRetryResult> {
  return platformClientRequest<RunRetryResult>(
    `/api/platform/runs/${encodeURIComponent(runId)}/retry`,
    '任务重试失败。',
    { method: 'POST' }
  );
}
