import 'server-only';

import { getFile } from '@/features/files/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import {
  platformServerRequest,
  platformServerResponse
} from '@/features/platform-api/server-client';
import type { RunApproval, RunDetail, RunPage, RunStep } from '@/features/platform-api/types';
import { getSkillCatalogItem } from '@/features/skills/api/server';
import type { PlatformRunDetail, RunOutputFile, RunMetricSpec } from './types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function checkedUuid(value: string, label: string): string {
  if (!UUID.test(value)) throw new PlatformApiError(400, `${label}格式无效。`);
  return value;
}

export function listRuns(page = 1, pageSize = 5, state = ''): Promise<RunPage> {
  const checkedPage = Math.max(Math.trunc(page), 1);
  const checkedPageSize = Math.min(Math.max(Math.trunc(pageSize), 1), 100);
  const params = new URLSearchParams({
    page: String(checkedPage),
    page_size: String(checkedPageSize)
  });
  if (state) params.set('state', state.slice(0, 40));
  return platformServerRequest<RunPage>(`/api/runs?${params}`);
}

export async function getRun(runId: string): Promise<PlatformRunDetail> {
  const run = await platformServerRequest<RunDetail>(`/api/runs/${checkedUuid(runId, '任务标识')}`);
  let metricSpecs: RunMetricSpec[] = [];
  try {
    const skill = await getSkillCatalogItem(run.skill_id);
    metricSpecs = skill.result_presentation?.metrics ?? [];
  } catch (error) {
    if (!(error instanceof PlatformApiError && error.status === 404)) throw error;
  }
  return { ...run, metric_specs: metricSpecs };
}

export function getRunSteps(runId: string): Promise<RunStep[]> {
  return platformServerRequest<RunStep[]>(`/api/runs/${checkedUuid(runId, '任务标识')}/steps`);
}

export function getRunApprovals(runId: string): Promise<RunApproval[]> {
  return platformServerRequest<RunApproval[]>(
    `/api/runs/${checkedUuid(runId, '任务标识')}/approvals`
  );
}

export function retryRun(runId: string): Promise<RunDetail> {
  return platformServerRequest<RunDetail>(`/api/runs/${checkedUuid(runId, '任务标识')}/retry`, {
    method: 'POST'
  });
}

export async function streamRunEvents(
  runId: string,
  after: number,
  signal: AbortSignal
): Promise<Response> {
  const checkedAfter = Number.isSafeInteger(after) && after >= 0 ? after : 0;
  return platformServerResponse(
    `/api/runs/${checkedUuid(runId, '任务标识')}/events?after=${checkedAfter}`,
    {
      headers: { Accept: 'text/event-stream' },
      signal
    },
    { timeoutMs: null }
  );
}

export async function downloadRunOutput(
  runId: string,
  fileId: string,
  signal: AbortSignal
): Promise<{ response: Response; file: RunOutputFile }> {
  const checkedRunId = checkedUuid(runId, '任务标识');
  const checkedFileId = checkedUuid(fileId, '文件标识');
  const fileRecord = await getFile(checkedFileId);
  if (
    fileRecord.run_id !== checkedRunId &&
    !(fileRecord.referenced_run_ids ?? []).includes(checkedRunId)
  ) {
    throw new PlatformApiError(404, '该文件不属于当前任务结果。');
  }
  const file: RunOutputFile = {
    fileId: fileRecord.id,
    name: fileRecord.name,
    sizeBytes: fileRecord.size_bytes,
    sha256: fileRecord.sha256
  };
  const response = await platformServerResponse(
    `/api/files/${checkedFileId}/download`,
    { signal },
    { timeoutMs: 120_000 }
  );
  return { response, file };
}
