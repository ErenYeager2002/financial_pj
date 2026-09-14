import type { AgentTool } from '@financial-platform/agent-runtime';
import { Type } from 'typebox';
import { sanitizePlatformInformation } from './platform-information-tool.ts';

type Requester = (path: string, body?: Record<string, unknown>) => Promise<unknown>;

export function createArWorkflowTools(
  input: { sessionId: string; message: string },
  request: Requester
): AgentTool[] {
  const skill = Type.Union([
    Type.Literal('ar-hexiao-daily'), Type.Literal('ar-hexiao-daily-lab')
  ]);
  const result = (value: unknown) => ({
    content: [{ type: 'text' as const, text: JSON.stringify(sanitizePlatformInformation('workflows', value)) }], details: {}
  });
  const context = { session_id: input.sessionId, message: input.message };
  return [
    {
      name: 'get_ar_request_status', label: '查询本次核销提交状态',
      description: '只读查询当前会话最后一条用户指令是否已提交及关联任务链接。启动超时、结果丢失或提示已提交时先调用，不要重复创建。',
      parameters: Type.Object({}),
      execute: async () => result(await request(
        `/api/assistant/ar/request?session_id=${encodeURIComponent(input.sessionId)}`
      ))
    },
    {
      name: 'inspect_ar_materials', label: '查询应收核销材料',
      description: '查询当前账号应收核销工具input及权威业务材料版本、缺失用途和智云凭据是否已配置。只读，不要求聊天附件，不返回凭据内容。',
      parameters: Type.Object({ skill_id: skill }),
      execute: async (_id, params) => result(await request(
        `/api/assistant/ar/materials?skill_id=${encodeURIComponent((params as { skill_id: string }).skill_id)}`
      ))
    },
    {
      name: 'prepare_ar_workflow', label: '检查核销启动条件',
      description: '为标准版或极速版核销检查明确日期及现有业务材料，固定本条用户指令的启动计划，不执行核销。用户明确要求执行时引用当前消息原文作为authorization_quote；纯查询留空。重跑成功日期只在用户明确要求重跑时设true，沿用此前对话明确的日期和版本。',
      parameters: Type.Object({
        skill_id: skill,
        reconciliation_dates: Type.Array(Type.String({ pattern: '^\\d{4}-\\d{2}-\\d{2}$' }), { minItems: 1, maxItems: 31 }),
        rerun_successful_dates: Type.Optional(Type.Boolean()),
        authorization_quote: Type.Optional(Type.String({ maxLength: 1000 }))
      }),
      execute: async (_id, params) => result(await request('/api/assistant/ar/prepare', {
        ...(params as Record<string, unknown>), ...context
      }))
    },
    {
      name: 'start_ar_workflow', label: '启动应收核销',
      description: '仅在用户已明确要求执行、prepare_ar_workflow返回ready及plan_id后启动。使用平台原有受控批次执行器，实时取数、按日期升序处理，保留权限、材料、并发与财务校验。已有授权无需再问确认；查询、假设、引用文字不是执行授权。失败或超时先查任务，不要自动再次提交。返回任务编号及可查看链接。',
      parameters: Type.Object({ plan_id: Type.String({ minLength: 1, maxLength: 64 }) }),
      execute: async (_id, params) => result(await request('/api/assistant/ar/start', {
        plan_id: (params as { plan_id: string }).plan_id, ...context
      }))
    }
  ];
}
