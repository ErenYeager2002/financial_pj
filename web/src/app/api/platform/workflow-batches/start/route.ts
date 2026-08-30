import { NextResponse } from 'next/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import { platformRouteError } from '@/features/platform-api/route-handler';
import type { WorkflowBatchRead } from '@/features/platform-api/types';
import {
  parseWorkflowFileBindings,
  parseWorkflowReplaceRoles
} from '@/features/workflow-agent/api/file-selection-request';

const ID = /^[A-Za-z0-9._-]+$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseBody(value: unknown): {
  skill_id: string;
  reconciliation_dates: string[];
  files: Record<string, string[]>;
  replace_roles: string[];
  rerun_successful_dates: boolean;
  rerun_reason: string;
  snapshot_workflow_id?: string;
} {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '批次任务请求格式无效。');
  }
  const body = value as Record<string, unknown>;
  const skillId = typeof body.skill_id === 'string' ? body.skill_id.trim() : '';
  const rawDates = body.reconciliation_dates;
  if (
    !ID.test(skillId) ||
    !Array.isArray(rawDates) ||
    rawDates.length < 1 ||
    rawDates.length > 31
  ) {
    throw new PlatformApiError(400, 'Skill 标识或日期选择格式无效。');
  }
  const dates = rawDates.map((item) => {
    if (typeof item !== 'string' || !DATE.test(item)) {
      throw new PlatformApiError(400, '日期格式无效。');
    }
    return item;
  });
  if (
    body.rerun_successful_dates !== undefined &&
    typeof body.rerun_successful_dates !== 'boolean'
  ) {
    throw new PlatformApiError(400, '重新核销选项格式无效。');
  }
  const rerunSuccessfulDates = body.rerun_successful_dates === true;
  const rerunReason = typeof body.rerun_reason === 'string' ? body.rerun_reason.trim() : '';
  if (rerunReason.length > 500) {
    throw new PlatformApiError(400, '重新核销原因不能超过 500 个字符。');
  }
  if (rerunSuccessfulDates && !rerunReason) {
    throw new PlatformApiError(400, '勾选重新核销已成功日期后，必须填写重新核销原因。');
  }
  const snapshotWorkflowId =
    body.snapshot_workflow_id === undefined
      ? undefined
      : typeof body.snapshot_workflow_id === 'string'
        ? body.snapshot_workflow_id.trim()
        : '';
  if (
    snapshotWorkflowId !== undefined &&
    (snapshotWorkflowId.length > 64 || !ID.test(snapshotWorkflowId))
  ) {
    throw new PlatformApiError(400, '取数快照标识格式无效。');
  }
  return {
    skill_id: skillId,
    reconciliation_dates: dates,
    files: parseWorkflowFileBindings(body.files),
    replace_roles: parseWorkflowReplaceRoles(body.replace_roles),
    rerun_successful_dates: rerunSuccessfulDates,
    rerun_reason: rerunReason,
    ...(snapshotWorkflowId ? { snapshot_workflow_id: snapshotWorkflowId } : {})
  };
}

export async function POST(request: Request): Promise<Response> {
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '批次任务请求不是有效的 JSON。');
    }
    const input = parseBody(body);
    const batch = await platformServerRequest<WorkflowBatchRead>('/api/workflow-batches/start', {
      method: 'POST',
      body: JSON.stringify(input)
    });
    return NextResponse.json(batch, { status: 201 });
  } catch (error) {
    return platformRouteError(error, '批次任务启动失败。');
  }
}
