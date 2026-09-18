export type UploadedFile = { name: string; agent_path: string };
export async function fileRequest<T>(sessionId: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/platform/pi-runtime/sessions/${encodeURIComponent(sessionId)}/files`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : typeof value.message === 'string' ? value.message : '文件操作失败');
  return value;
}
export async function uploadFile(sessionId: string, file: File, progress: (percent: number) => void, signal?: AbortSignal): Promise<UploadedFile> {
  let id = '';
  try {
    const initial = await fileRequest<{upload_id: string}>(sessionId, {action: 'upload_begin', name: file.name, size: file.size}, signal);
    id = initial.upload_id;
    for (let offset = 0; offset < file.size; offset += 1024 * 1024) {
      const bytes = new Uint8Array(await file.slice(offset, offset + 1024 * 1024).arrayBuffer());
      let raw = '';
      for (let at = 0; at < bytes.length; at += 8192) raw += String.fromCharCode(...bytes.subarray(at, at + 8192));
      await fileRequest(sessionId, {action: 'upload_chunk', upload_id: id, offset, data: btoa(raw)}, signal);
      progress(Math.round(Math.min(file.size, offset + bytes.length) / file.size * 100));
    }
    const done = await fileRequest<{agent_path: string}>(sessionId, {action: 'upload_commit', upload_id: id}, signal);
    id = ''; progress(100);
    return {name: file.name, agent_path: done.agent_path};
  } catch (error) {
    if (id) await fileRequest(sessionId, {action: 'upload_abort', upload_id: id}).catch(() => {});
    throw error;
  }
}

export function fileDownloadUrl(sessionId: string, source: string, path: string) {
  return `/api/platform/pi-runtime/sessions/${encodeURIComponent(sessionId)}/download?${new URLSearchParams({source, path})}`;
}
export function resolveAgentFile(sessionId: string, href: string): string | undefined {
  let value: string;
  try { value = decodeURIComponent(href); } catch { return; }
  const match = /^(?:sandbox:)?\/(workspace|inputs)\/(.+)$/.exec(value);
  if (!match || match[2].split('/').some(part => !part || part === '.' || part === '..') || /[\\\x00-\x1f]/.test(match[2])) return;
  return fileDownloadUrl(sessionId, match[1], match[2]);
}
