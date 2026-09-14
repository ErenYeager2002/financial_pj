export function watchAssistantTurn(
  sessionId: string,
  callbacks: {
    update: (conversation: unknown, active: boolean) => void;
    error: (message: string) => void;
  },
  request: typeof fetch = fetch,
  interval = 2000
): () => void {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const options = { cache: 'no-store' as const, signal: controller.signal };
  async function poll() {
    let again = true;
    try {
      const response = await request(`/api/platform/assistant/turn?session_id=${encodeURIComponent(sessionId)}`, options);
      if (!response.ok) throw new Error('回复状态暂时无法同步，请稍候。');
      const status = await response.json() as { active: boolean; error?: string };
      const historyResponse = await request(`/api/platform/assistant/conversations/${encodeURIComponent(sessionId)}`, options);
      if (!historyResponse.ok) throw new Error('回复记录暂时无法同步，请稍候。');
      const history: unknown = await historyResponse.json();
      if (controller.signal.aborted) return;
      callbacks.update(history, status.active);
      if (status.error) callbacks.error(status.error);
      again = status.active;
    } catch {
      if (!controller.signal.aborted) callbacks.error('回复状态暂时无法同步，请稍候；不要重复发送执行指令。');
    } finally {
      if (again && !controller.signal.aborted) timer = setTimeout(() => { void poll(); }, interval);
    }
  }
  void poll();
  return () => { controller.abort(); if (timer) clearTimeout(timer); };
}
