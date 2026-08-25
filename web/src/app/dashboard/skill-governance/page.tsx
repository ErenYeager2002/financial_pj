import { Suspense } from 'react';
import { HydrationBoundary, dehydrate } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import {
  listSkillAvailability,
  listSkillSourceBindings
} from '@/features/admin/api/skill-releases';
import { platformServerRequest } from '@/features/platform-api/server-client';
import type { PlatformSession } from '@/features/platform-api/types';
import {
  observabilityQueryOptions,
  workflowDefinitionsQueryOptions
} from '@/features/skill-governance/api/queries';
import {
  getObservabilitySummary,
  listWorkflowDefinitions
} from '@/features/skill-governance/api/server';
import { SkillGovernanceData } from '@/features/skill-governance/components/skill-governance-data';
import { SkillGovernanceSkeleton } from '@/features/skill-governance/components/skill-governance-skeleton';
import { SkillSourceManagement } from '@/features/skills/components/skill-source-management';
import { getQueryClient } from '@/lib/query-client';

export const metadata = {
  title: 'Skill 发布与维护'
};

export default async function SkillGovernancePage(): Promise<React.JSX.Element> {
  const session = await platformServerRequest<PlatformSession>('/api/session');
  if (session.role !== 'skill_admin') {
    return (
      <PageContainer
        access={false}
        accessFallback={<p className='text-muted-foreground'>只有平台管理员可以维护 Skill。</p>}
      >
        {null}
      </PageContainer>
    );
  }

  const queryClient = getQueryClient();
  const hours = 24;
  void queryClient.prefetchQuery(workflowDefinitionsQueryOptions(listWorkflowDefinitions));
  void queryClient.prefetchQuery(
    observabilityQueryOptions(hours, () => getObservabilitySummary(hours))
  );
  const [bindings, availabilityItems] = await Promise.all([
    listSkillSourceBindings(),
    listSkillAvailability()
  ]);
  const availability = Object.fromEntries(availabilityItems.map((item) => [item.skill_id, item]));
  return (
    <PageContainer
      pageTitle='Skill 发布与维护'
      pageDescription='禁用 Skill 后从 Gitee 拉取最新代码，更新成功后自动重新启用'
    >
      <div className='space-y-6'>
        <SkillSourceManagement initialBindings={bindings} initialAvailability={availability} />
        <HydrationBoundary state={dehydrate(queryClient)}>
          <Suspense fallback={<SkillGovernanceSkeleton />}>
            <SkillGovernanceData hours={hours} />
          </Suspense>
        </HydrationBoundary>
      </div>
    </PageContainer>
  );
}
