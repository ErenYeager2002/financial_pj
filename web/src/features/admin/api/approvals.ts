import 'server-only';

import { PlatformApiError } from '@/features/platform-api/errors';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type {
  ApprovalDecisionRequest,
  ApprovalRecord,
  PlatformSession
} from '@/features/platform-api/types';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STATUSES = new Set(['', 'pending', 'approved', 'rejected', 'expired', 'revoked']);

async function requirePlatformAdmin(): Promise<void> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    throw new PlatformApiError(403, '只有平台管理员可以查看和处理写入审批。');
  }
}

function objectBody(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '审批请求格式无效。');
  }
  return value as Record<string, unknown>;
}

export async function listApprovals(status = ''): Promise<ApprovalRecord[]> {
  await requirePlatformAdmin();
  const selected = STATUSES.has(status) ? status : '';
  const query = selected ? `?status=${encodeURIComponent(selected)}` : '';
  return platformServerRequest<ApprovalRecord[]>(`/api/admin/approvals${query}`);
}

export async function decideApproval(approvalId: string, value: unknown): Promise<ApprovalRecord> {
  await requirePlatformAdmin();
  if (!UUID.test(approvalId)) throw new PlatformApiError(400, '审批记录标识格式无效。');
  const body = objectBody(value);
  if (body.decision !== 'approve' && body.decision !== 'reject') {
    throw new PlatformApiError(400, '审批结果只能是批准或拒绝。');
  }
  const decision = body.decision;
  const reason = typeof body.reason === 'string' ? body.reason.trim() : '';
  if (reason.length < 2 || reason.length > 2000) {
    throw new PlatformApiError(400, '审批意见必须为 2 到 2000 个字符。');
  }
  const request: ApprovalDecisionRequest = { decision, reason };
  return platformServerRequest<ApprovalRecord>(`/api/admin/approvals/${approvalId}/decision`, {
    method: 'POST',
    body: JSON.stringify(request)
  });
}
