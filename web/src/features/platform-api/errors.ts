import type { SubmissionErrorDetail } from './generated';

const submissionMessages: Record<SubmissionErrorDetail['code'], string> = {
  SUBMISSION_RECOVERY_ONLY: '平台处于提交恢复模式，暂不接受新任务。已创建的任务仍可查询。',
  LEGACY_SUBMISSION_UNVERIFIED: '该提交标识已有历史任务，请先核查历史任务；系统未创建新任务。',
  IDEMPOTENCY_CONFLICT: '同一提交标识不能用于不同内容，请修改后重新提交。',
  SUBMISSION_IN_PROGRESS: '任务正在准备，请稍后再次查询或使用原提交重试。',
  SUBMISSION_NOT_READY: '提交状态已变化，请稍后使用原提交重试。',
  SUBMISSION_REJECTED: '本次提交已被拒绝，请检查输入。'
};

function isSubmissionCode(value: unknown): value is SubmissionErrorDetail['code'] {
  return typeof value === 'string' && Object.hasOwn(submissionMessages, value);
}

export class PlatformApiError extends Error {
  readonly status: number;
  readonly detail?: SubmissionErrorDetail;
  constructor(status: number, message: string, detail?: SubmissionErrorDetail) {
    super(message);
    this.name = 'PlatformApiError';
    this.status = status;
    this.detail = detail;
  }
}

export function platformApiError(status: number, body: unknown, fallback: string): PlatformApiError {
  const message = platformErrorMessage(body, fallback);
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = body.detail;
    if (typeof detail === 'object' && detail !== null && 'code' in detail &&
        isSubmissionCode(detail.code)) {
      const safe: SubmissionErrorDetail = { code: detail.code, message };
      if ('request_id' in detail && typeof detail.request_id === 'string' &&
          /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(detail.request_id)) {
        safe.request_id = detail.request_id;
      }
      return new PlatformApiError(status, message, safe);
    }
  }
  return new PlatformApiError(status, message);
}

export function platformErrorBody(error: PlatformApiError) {
  return { detail: error.detail ?? error.message };
}

export function platformErrorMessage(body: unknown, fallback: string): string {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return fallback;
  const detail = body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail.filter((item): item is string => typeof item === 'string');
    if (messages.length) return messages.join('；');
  }
  if (
    typeof detail === 'object' &&
    detail !== null &&
    'message' in detail &&
    typeof detail.message === 'string'
  ) {
    return detail.message;
  }
  if (typeof detail === 'object' && detail !== null && 'code' in detail &&
      isSubmissionCode(detail.code)) {
    return submissionMessages[detail.code];
  }
  return fallback;
}
