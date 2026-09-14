import { beginTurn, attachTurn, finishTurn, stopTurn, turnStatus } from '@/features/ai-chat/turn-state';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import { createAssistantTurn } from '@/features/ai-chat/agent-server';
import { appendAssistantMessage } from '@/features/ai-chat/api/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

function requestInput(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, 'AI 会话请求格式无效。');
  }
  const body = value as Record<string, unknown>;
  const sessionId = typeof body.session_id === 'string' ? body.session_id : '';
  const message = typeof body.message === 'string' ? body.message : '';
  const fileIds = Array.isArray(body.file_ids) ? body.file_ids : [];
  if (fileIds.some((item) => typeof item !== 'string')) {
    throw new PlatformApiError(400, '所选文件标识无效。');
  }
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(sessionId)) throw new PlatformApiError(400, 'AI 会话标识格式无效。');
  return { sessionId, message, fileIds: fileIds as string[] };
}

function eventFrame(event: unknown): string {
  const type =
    typeof event === 'object' && event !== null && 'type' in event && typeof event.type === 'string'
      ? event.type
      : 'message';
  return `event: ${type}\ndata: ${JSON.stringify(event)}\n\n`;
}

export async function POST(request: Request): Promise<Response> {
  let input: ReturnType<typeof requestInput> | undefined;
  let userMessageSaved = false;
  let entry: NonNullable<ReturnType<typeof beginTurn>> | undefined;
  let turn: Awaited<ReturnType<typeof createAssistantTurn>>;
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, 'AI 会话请求不是有效的 JSON。');
    }
    input = requestInput(body);
    const owner = await platformServerRequest<PlatformSession>('/api/session');
    const pending = beginTurn(owner.user_id, input.sessionId);
    if (!pending) throw new PlatformApiError(409, '当前会话仍在生成回复，请等待完成或点击停止。');
    entry = pending;
    await appendAssistantMessage(input.sessionId, 'user', input.message);
    userMessageSaved = true;
    turn = await createAssistantTurn(input);
    attachTurn(entry, turn.abort);
  } catch (error) {
    if (userMessageSaved && input) {
      await appendAssistantMessage(input.sessionId, 'assistant', '本次请求未能启动，请稍后重试。').catch(
        () => undefined
      );
    }
    if (entry) finishTurn(entry, '本次请求未能启动。');
    return platformRouteError(error, 'AI 助手会话启动失败。');
  }

  const encoder = new TextEncoder();
  let connected = !request.signal.aborted;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const detach = () => { connected = false; };
      request.signal.addEventListener('abort', detach, { once: true });
      const emit = (event: unknown) => {
        if (!connected) return;
        try { controller.enqueue(encoder.encode(eventFrame(event))); }
        catch { connected = false; }
      };
      let assistantText = '';
      let streamError = '';
      let persistenceError = '';
      try {
        // Browser navigation detaches this subscriber, not the server's turn.
        for await (const event of turn.events) {
          if (event.type === 'text_delta') assistantText += event.delta;
          if (event.type === 'error') streamError = event.message;
          emit(event);
        }
      } catch (error) {
        streamError = error instanceof PlatformApiError ? error.message : 'AI 助手会话处理失败。';
        emit({ type: 'error', code: 'assistant_stream_error', message: streamError });
      } finally {
        const persistedText = assistantText.trim() || (entry!.stopped ? '已停止生成。' : streamError) || '本次请求已处理。';
        try {
          await appendAssistantMessage(input!.sessionId, 'assistant', persistedText);
        } catch {
          persistenceError = '回复已生成，但聊天记录暂时保存失败。请先核实任务状态，不要重复发送执行指令。';
          emit({ type: 'error', code: 'assistant_history_save_failed', message: persistenceError });
        }
        // Recovery polling must not see completion before history is saved.
        finishTurn(entry!, persistenceError);
        request.signal.removeEventListener('abort', detach);
        if (connected) {
          try { controller.close(); } catch { /* The subscriber already left. */ }
        }
      }
    },
    cancel() { connected = false; }
  });

  return new Response(stream, {
    headers: {
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'Content-Type': 'text/event-stream; charset=utf-8',
      'X-Accel-Buffering': 'no'
    }
  });
}


export async function GET(request: Request): Promise<Response> {
  try {
    const sessionId = new URL(request.url).searchParams.get('session_id') ?? '';
    requestInput({ session_id: sessionId });
    const owner = await platformServerRequest<PlatformSession>('/api/session');
    return Response.json(turnStatus(owner.user_id, sessionId), { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) { return platformRouteError(error, '回复状态查询失败。'); }
}

export async function DELETE(request: Request): Promise<Response> {
  try {
    const input = requestInput(await request.json());
    const owner = await platformServerRequest<PlatformSession>('/api/session');
    stopTurn(owner.user_id, input.sessionId);
    return Response.json({ stopped: true });
  } catch (error) { return platformRouteError(error, '停止生成失败。'); }
}
