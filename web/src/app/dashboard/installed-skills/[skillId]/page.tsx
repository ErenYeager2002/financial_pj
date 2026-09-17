import { redirect } from 'next/navigation';
export default async function Page({ params }: { params: Promise<{ skillId: string }> }) { const {skillId} = await params; redirect(`/dashboard/installed-skills/${encodeURIComponent(skillId)}/run`); }
