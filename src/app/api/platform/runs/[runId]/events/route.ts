import { platformRouteError } from '@/features/platform-api/route-handler';
import { streamRunEvents } from '@/features/runs/api/server';

type Params = { params: Promise<{ runId: string }> };

function eventCursor(request: Request): number {
  const urlCursor = new URL(request.url).searchParams.get('after');
  const headerCursor = request.headers.get('last-event-id');
  const raw = headerCursor || urlCursor || '0';
  if (!/^\d+$/.test(raw)) return 0;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

export async function GET(request: Request, { params }: Params) {
  try {
    const { runId } = await params;
    const upstream = await streamRunEvents(runId, eventCursor(request), request.signal);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        'Cache-Control': 'no-cache, no-transform',
        'Content-Type': 'text/event-stream; charset=utf-8',
        'X-Accel-Buffering': 'no'
      }
    });
  } catch (error) {
    return platformRouteError(error, '任务事件流连接失败。');
  }
}
