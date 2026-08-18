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
  let turn: Awaited<ReturnType<typeof createAssistantTurn>>;
  try {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, 'AI 会话请求不是有效的 JSON。');
    }
    input = requestInput(body);
    await appendAssistantMessage(input.sessionId, 'user', input.message);
    userMessageSaved = true;
    turn = await createAssistantTurn(input);
  } catch (error) {
    if (userMessageSaved && input) {
      await appendAssistantMessage(input.sessionId, 'assistant', '本次请求未能启动，请稍后重试。').catch(
        () => undefined
      );
    }
    return platformRouteError(error, 'AI 助手会话启动失败。');
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const abort = () => turn.abort();
      request.signal.addEventListener('abort', abort, { once: true });
      let assistantText = '';
      let streamError = '';
      try {
        for await (const event of turn.events) {
          if (event.type === 'text_delta') assistantText += event.delta;
          if (event.type === 'error') streamError = event.message;
          controller.enqueue(encoder.encode(eventFrame(event)));
        }
      } catch (error) {
        const message = error instanceof PlatformApiError ? error.message : 'AI 助手会话处理失败。';
        streamError = message;
        controller.enqueue(
          encoder.encode(eventFrame({ type: 'error', code: 'assistant_stream_error', message }))
        );
      } finally {
        const persistedText = assistantText.trim() || streamError || '本次请求已处理。';
        try {
          await appendAssistantMessage(input!.sessionId, 'assistant', persistedText);
        } catch {
          controller.enqueue(
            encoder.encode(
              eventFrame({
                type: 'error',
                code: 'assistant_history_save_failed',
                message: '回复已生成，但聊天记录暂时保存失败。'
              })
            )
          );
        }
        request.signal.removeEventListener('abort', abort);
        controller.close();
      }
    },
    cancel() {
      turn.abort();
    }
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
