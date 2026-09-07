import { resultDetailsResponse } from '@/features/workflow-agent/api/result-details-route';

export async function GET(request: Request, { params }: { params: Promise<{ batchId: string }> }): Promise<Response> {
  const { batchId } = await params;
  return resultDetailsResponse(request, 'workflow-batches', batchId);
}
