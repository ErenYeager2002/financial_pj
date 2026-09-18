import PageContainer from '@/components/layout/page-container';
import {PiChat} from '@/features/pi-runtime/pi-chat';
import type {PiSession} from '@/features/pi-runtime/pi-workspace';
import {platformServerRequest} from '@/features/platform-api/server-client';
export const metadata={title:'AI 助手'};
export default async function Page({searchParams}:{searchParams:Promise<{session?:string}>}){
 const query=await searchParams;
 const sessions=await platformServerRequest<PiSession[]>('/api/pi-runtime/sessions');
 return <PageContainer compact>
  <PiChat initialSessions={sessions.filter(item=>!item.skill_id&&item.channel!=='workspace')} initialSessionId={query.session}/>
 </PageContainer>;
}
