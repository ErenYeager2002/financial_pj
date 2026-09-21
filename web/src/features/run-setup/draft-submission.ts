import type { ConfirmTaskDraftInput } from './api/types';

function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([key,item]) => [key,ordered(item)]));
  }
  return value;
}

export function sameDraftInput(value: unknown, input: ConfirmTaskDraftInput): boolean {
  if (typeof value !== 'object' || value === null || !('state' in value) ||
      !('parameters' in value) || !('files' in value)) return false;
  const recoverable = value.state === 'ready' ||
    (value.state === 'consumed' && 'run_id' in value && typeof value.run_id === 'string' && Boolean(value.run_id));
  if (!recoverable) return false;
  return JSON.stringify(ordered(value.parameters)) === JSON.stringify(ordered(input.parameters)) &&
    JSON.stringify(ordered(value.files)) === JSON.stringify(ordered(input.files));
}

export async function submitDraftRequest(input: ConfirmTaskDraftInput, request: typeof fetch = fetch): Promise<Response> {
  const path = `/api/platform/task-drafts/${encodeURIComponent(input.draftId)}`;
  const update = await request(path, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({parameters:input.parameters,files:input.files})
  });
  if (!update.ok) {
    if (update.status !== 409) return update;
    // Publication may reject PATCH for an unchanged prepared draft. A lost
    // response may leave it consumed. POST rechecks receipt, scope and files;
    // only exact unchanged input can take either recovery path.
    const current = await request(path, {cache:'no-store'});
    if (!current.ok) return update;
    let body: unknown;
    try { body = await current.json(); } catch { return update; }
    if (!sameDraftInput(body,input)) return update;
  }
  return request(`${path}/confirm`, {method:'POST'});
}
