import { createChat } from '@shadcn/helpers/ai-sdk';
import type { UIMessage } from 'ai';

type Tools = {
  getRevenue: {
    input: { period: string };
    output: {
      period: string;
      revenue: number;
      changePct: number;
      topDriver: string;
    };
  };
};

/** The message shape for this demo (typed tools, no data parts). */
export type DemoUIMessage = UIMessage<unknown, Record<string, never>, Tools>;

/**
 * A scripted AI conversation. It streams through the real `useChat` lifecycle
 * via `transport()` — no model, API route, network request, or API key. The
 * script shows off reasoning, a tool call, and streamed text across two turns.
 */
export const demoChat = createChat<unknown, Record<string, never>, Tools>()
  .user('上个月的收入表现如何？接下来应该重点关注什么？')
  .sleep(500)
  .assistant(({ writer }) => {
    writer.reasoning(
      '用户询问上月收入趋势和后续建议。我先从指标工具获取数据，再根据结果给出建议。'
    );
    writer
      .tool('getRevenue', {
        title: '正在获取收入指标',
        input: { period: 'last-month' }
      })
      .sleep(900)
      .output({
        period: 'last-month',
        revenue: 1250,
        changePct: 12.5,
        topDriver: '回头客'
      });
    writer.text('上个月收入为 1,250 美元，较前一个月增长 12.5%，收入保持上升趋势。');
    writer.text('主要增长来自回头客。');
  })
  .user('很好，接下来应该把精力放在哪里？')
  .sleep(500)
  .assistant(({ writer }) => {
    writer.reasoning(
      '收入状况良好，增长主要由留存客户推动，目前短板是新客户获取。我会给出一项具体且易于执行的建议。'
    );
    writer.text(
      '回头客在推动增长，因此建议重点改善新客户获取。本期新客户减少约 20%，可以尝试推荐奖励或小规模定向活动，以较低成本改善获客情况。'
    );
  });

/** Empty initial transcript — the demo streams as the user presses Send. */
export const initialMessages = demoChat.get(0);

/** Local transport that streams the scripted responses through `useChat`. */
export const chatTransport = demoChat.transport({ delayMs: 30 });
