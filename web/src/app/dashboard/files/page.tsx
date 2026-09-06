import PageContainer from '@/components/layout/page-container';
import { listFileGroups, listFiles } from '@/features/files/api/server';
import { FileList } from '@/features/files/components/file-list';
import {
  parseFileCenterSearchParams,
  resolveFileCenterState,
  type FileCenterSearchParams
} from '@/features/files/file-center-pagination';
import type { PlatformFilePage } from '@/features/platform-api/types';

export const metadata = {
  title: '文件中心'
};

type PageProps = {
  searchParams: Promise<FileCenterSearchParams>;
};

export default async function Page({ searchParams }: PageProps) {
  const queryState = parseFileCenterSearchParams(await searchParams);
  const groupPage = await listFileGroups({
    kind: queryState.kind,
    query: queryState.query,
    latestOnly: true
  });
  const groups = groupPage.items ?? [];
  const resolved = resolveFileCenterState(queryState, groups);
  const filePage: PlatformFilePage = resolved.activeGroup
    ? await listFiles({
        page: resolved.page,
        pageSize: resolved.pageSize,
        kind: resolved.kind,
        query: resolved.query,
        includeDeleteStatus: true,
        skillId: resolved.activeGroup.unassigned ? '' : resolved.activeGroup.skill_id,
        unassigned: resolved.activeGroup.unassigned
      })
    : {
        items: [],
        total: 0,
        page: 1,
        page_size: resolved.pageSize,
        pages: 0
      };

  return (
    <PageContainer pageTitle='文件中心' headingLevel={1} compact>
      <FileList
        groups={groups}
        groupTotal={groupPage.total_groups}
        fileTotal={groupPage.total_files}
        page={filePage}
        kind={resolved.kind}
        query={resolved.query}
        activeGroup={resolved.activeGroup}
        shouldCanonicalizeUrl={
          !resolved.requestedGroupFound ||
          resolved.page !== resolved.requestedPage ||
          resolved.pageWasNormalized
        }
      />
    </PageContainer>
  );
}
