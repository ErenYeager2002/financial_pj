import { PlatformApiError } from '@/features/platform-api/errors';

const ROLE_ID = /^[A-Za-z0-9._-]+$/;
const FILE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function parseWorkflowFileBindings(
  value: unknown,
  options: { required?: boolean } = {}
): Record<string, string[]> {
  if (value === undefined && !options.required) return {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '文件绑定格式无效。');
  }
  const files: Record<string, string[]> = {};
  for (const [role, ids] of Object.entries(value)) {
    if (!ROLE_ID.test(role) || !Array.isArray(ids) || ids.length > 100) {
      throw new PlatformApiError(400, '文件绑定格式无效。');
    }
    files[role] = ids.map((fileId) => {
      if (typeof fileId !== 'string' || !FILE_UUID.test(fileId)) {
        throw new PlatformApiError(400, '文件标识格式无效。');
      }
      return fileId;
    });
  }
  return files;
}

export function parseWorkflowReplaceRoles(value: unknown): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 100) {
    throw new PlatformApiError(400, '文件替换角色格式无效。');
  }
  return value.map((role) => {
    if (typeof role !== 'string' || !ROLE_ID.test(role)) {
      throw new PlatformApiError(400, '文件替换角色格式无效。');
    }
    return role;
  });
}
