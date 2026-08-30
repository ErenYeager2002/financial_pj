import assert from 'node:assert/strict';
import test from 'node:test';
import { draftCompletionMessage } from '../src/features/ai-chat/assistant-message.ts';

test('tool-only draft completion replaces the empty assistant spinner with useful text', () => {
  assert.equal(
    draftCompletionMessage('', '银行流水自动对账'),
    '任务草稿已生成：银行流水自动对账。请在右侧核对后打开任务。'
  );
  assert.equal(draftCompletionMessage('模型已有回复', '银行流水自动对账'), '模型已有回复');
});
