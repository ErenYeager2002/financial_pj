import { redirect } from 'next/navigation';

interface PageProps {
  params: Promise<{ skillId: string; taskId: string }>;
}

export default async function Page({ params }: PageProps): Promise<never> {
  const { taskId } = await params;
  redirect(`/dashboard/runs/${encodeURIComponent(taskId)}`);
}
