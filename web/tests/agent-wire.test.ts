import test from 'node:test';
import assert from 'node:assert/strict';
import { parseAgentWireEvent } from '../src/features/agent-runtime/agent-wire.ts';

test('parses a typed tool result event', () => {
  const event = parseAgentWireEvent({
    type: 'tool_result',
    toolCallId: 'call-1',
    toolName: 'prepare_task_draft',
    isError: false,
    awaitConfirmation: false,
    details: { draft: { id: 'draft-1' } }
  });

  assert.equal(event.type, 'tool_result');
  assert.equal(event.toolName, 'prepare_task_draft');
});

test('rejects malformed or unknown events before UI state changes', () => {
  assert.throws(() => parseAgentWireEvent({ type: 'text_delta', delta: 1 }));
  assert.throws(() => parseAgentWireEvent({ type: 'unknown' }));
});
