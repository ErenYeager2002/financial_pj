import {redirect} from 'next/navigation';

export default async function Page({searchParams}: {searchParams: Promise<{session?: string}>}) {
  const {session} = await searchParams;
  redirect('/dashboard/ai-chat' + (session ? '?session=' + encodeURIComponent(session) : ''));
}
