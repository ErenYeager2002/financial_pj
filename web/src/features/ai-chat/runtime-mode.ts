export type AgentRuntimeMode = 'legacy' | 'pi';

import type { AgentEvent } from '@financial-platform/agent-runtime';

interface RuntimeEnvironment {
  [key: string]: string | undefined;
}

export function runtimeSelectorId(
  clerkUserId: string | null | undefined,
  platformUserId: string
): string {
  const normalizedClerkUserId = clerkUserId?.trim();
  return normalizedClerkUserId || platformUserId;
}

export function resolveAgentRuntime(
  userId: string,
  environment: RuntimeEnvironment = process.env
): AgentRuntimeMode {
  const configured = environment.AGENT_RUNTIME?.trim().toLowerCase();
  if (configured === 'pi' || !configured) {
    return 'pi';
  }

  const piUsers = new Set(
    (environment.AGENT_RUNTIME_PI_USERS ?? '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  );
  return piUsers.has(userId) ? 'pi' : 'legacy';
}

export function legacyFallbackEnabled(environment: RuntimeEnvironment = process.env): boolean {
  const value = environment.AGENT_RUNTIME_FALLBACK?.trim().toLowerCase();
  return value === 'legacy' || value === 'true';
}

function hasStartedWork(event: AgentEvent): boolean {
  return (
    event.type === 'text_delta' ||
    event.type === 'tool_start' ||
    event.type === 'tool_result' ||
    event.type === 'await_confirmation'
  );
}

export async function* withLegacyFallback(
  piEvents: AsyncIterable<AgentEvent>,
  legacyEvents: () => AsyncIterable<AgentEvent>,
  environment: RuntimeEnvironment = process.env
): AsyncIterable<AgentEvent> {
  let startedWork = false;
  for await (const event of piEvents) {
    if (event.type === 'done' && !startedWork) {
      if (legacyFallbackEnabled(environment)) {
        try {
          yield* legacyEvents();
        } catch {
          yield {
            type: 'error',
            code: 'legacy_fallback_failed',
            message: 'AI 助手和旧实现当前都不可用。'
          };
        }
      } else {
        yield {
          type: 'error',
          code: 'assistant_no_response',
          message: 'AI 助手没有返回内容，请重试。'
        };
      }
      return;
    }
    if (hasStartedWork(event)) startedWork = true;
    if (event.type !== 'error' || startedWork || !legacyFallbackEnabled(environment)) {
      yield event;
      continue;
    }

    try {
      yield* legacyEvents();
    } catch {
      yield {
        type: 'error',
        code: 'legacy_fallback_failed',
        message: 'AI 助手和旧实现当前都不可用。'
      };
    }
    return;
  }
}
