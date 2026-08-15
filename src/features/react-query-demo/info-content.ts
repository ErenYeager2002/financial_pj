import type { InfobarContent } from '@/components/ui/infobar';

export const reactQueryInfoContent: InfobarContent = {
  title: 'React Query 使用模式',
  sections: [
    {
      title: '服务端预取',
      description:
        '服务端使用 getQueryClient().prefetchQuery() 预取数据，并通过 HydrationBoundary 将缓存传给客户端，因此首次加载时无需显示加载动画。',
      links: [
        {
          title: 'TanStack Query SSR 文档',
          url: 'https://tanstack.com/query/latest/docs/framework/react/guides/advanced-ssr'
        }
      ]
    },
    {
      title: '查询配置',
      description:
        '查询键和请求函数定义在共享的 queryOptions() 对象中，服务端预取和客户端钩子复用同一配置。',
      links: [
        {
          title: 'queryOptions API',
          url: 'https://tanstack.com/query/latest/docs/framework/react/reference/queryOptions'
        }
      ]
    },
    {
      title: 'Suspense 查询',
      description:
        '客户端使用与 React Suspense 集成的 useSuspenseQuery()。结合服务端预取，数据可立即使用；缓存失效后再次进入页面时才会显示占位内容。',
      links: []
    },
    {
      title: '乐观更新',
      description:
        '数据变更通过 onMutate 在请求完成前更新缓存。请求失败时恢复原状态，完成后使查询失效并重新获取最新数据。',
      links: [
        {
          title: '乐观更新指南',
          url: 'https://tanstack.com/query/latest/docs/framework/react/guides/optimistic-updates'
        }
      ]
    }
  ]
};
