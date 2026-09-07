import { resultDetailsResponse } from '@/features/workflow-agent/api/result-details-route';

export async function GET(request: Request, { params }: { params: Promise<{ workflowId: string }> }): Promise<Response> {
  const { workflowId } = await params;
  return resultDetailsResponse(request, 'workflows', workflowId);
}
