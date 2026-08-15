import type { InfobarContent } from '@/components/ui/infobar';

export const usersInfoContent: InfobarContent = {
  title: '用户管理：React Query 与 nuqs 模式',
  sections: [
    {
      title: '功能说明',
      description:
        '此页面演示 React Query 客户端数据请求与 nuqs URL 参数的组合用法。产品页面使用服务端 RSC 请求，两种模式共用 DataTable、useDataTable 钩子和 nuqs URL 状态。',
      links: [
        {
          title: 'TanStack Query SSR 文档',
          url: 'https://tanstack.com/query/latest/docs/framework/react/guides/advanced-ssr'
        }
      ]
    },
    {
      title: '服务端预取与客户端注水',
      description:
        '服务端组件通过 searchParamsCache 读取参数并构建筛选条件，再调用 queryClient.prefetchQuery()。缓存状态通过 HydrationBoundary 传给客户端，客户端使用相同参数调用 useSuspenseQuery。',
      links: []
    },
    {
      title: '使用 nuqs 管理 URL 状态',
      description:
        '分页、搜索和角色筛选通过 nuqs 同步到 URL。useDataTable 管理表格状态并延迟更新筛选参数；URL 变化后，React Query 根据包含筛选条件的查询键自动重新请求。',
      links: [
        {
          title: 'nuqs 文档',
          url: 'https://nuqs.47ng.com'
        }
      ]
    },
    {
      title: '产品与用户页面模式对比',
      description:
        '产品页面通过 searchParams、RSC 请求后把数据传给客户端表格；用户页面通过服务端预取、HydrationBoundary 和客户端 useSuspenseQuery 获取数据。用户页面模式支持后台刷新、组件间缓存共享和乐观更新。',
      links: []
    }
  ]
};
