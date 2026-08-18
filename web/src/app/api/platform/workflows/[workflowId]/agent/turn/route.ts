import { createWorkflowAgentTurn } from '@/features/workflow-agent/server';
import { PlatformApiError } from '@/features/platform-api/errors';
import { platformRouteError } from '@/features/platform-api/route-handler';

interface Params {
  params: Promise<{ workflowId: string }>;
}

function eventFrame(event: unknown): string {
  const type =
    typeof event === 'object' && event !== null && 'type' in event && typeof event.type === 'string'
      ? event.type
      : 'message';
  return `event: ${type}\ndata: ${JSON.stringify(event)}\n\n`;
}

function requestInput(workflowId: string, value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PlatformApiError(400, '工作流 Agent 请求格式无效。');
  }
  const body = value as Record<string, unknown>;
  const sessionId = typeof body.session_id === 'string' ? body.session_id : '';
  const message = typeof body.message === 'string' ? body.message : '';
  return { workflowId, sessionId, message };
}

export async function POST(request: Request, { params }: Params): Promise<Response> {
  let turn: Awaited<ReturnType<typeof createWorkflowAgentTurn>>;
  try {
    const { workflowId } = await params;
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      throw new PlatformApiError(400, '工作流 Agent 请求不是有效的 JSON。');
    }
    turn = await createWorkflowAgentTurn(requestInput(workflowId, body));
  } catch (error) {
    return platformRouteError(error, '工作流 Agent 会话启动失败。');
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const abort = () => turn.abort();
      request.signal.addEventListener('abort', abort, { once: true });
      try {
        for await (const event of turn.events) {
          controller.enqueue(encoder.encode(eventFrame(event)));
        }
      } catch {
        controller.enqueue(
          encoder.encode(
            eventFrame({
              type: 'error',
              code: 'workflow_agent_stream_error',
              message: '工作流 Agent 会话处理失败。'
            })
          )
        );
      } finally {
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
