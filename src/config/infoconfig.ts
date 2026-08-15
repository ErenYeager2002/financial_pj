import type { InfobarContent } from '@/components/ui/infobar';

export const workspacesInfoContent: InfobarContent = {
  title: '企业空间管理',
  sections: [
    {
      title: '功能说明',
      description:
        '企业空间页面用于查看、新建和切换企业空间。该功能由 Clerk Organizations 提供多租户组织管理能力。',
      links: [
        {
          title: 'Clerk Organizations 文档',
          url: 'https://clerk.com/docs/organizations/overview'
        }
      ]
    },
    {
      title: '创建企业空间',
      description:
        '点击创建组织按钮，填写企业空间名称并完成初始设置。创建后可以切换到该空间并进行管理。',
      links: [
        {
          title: '多租户身份验证指南',
          url: 'https://clerk.com/blog/how-to-build-multitenant-authentication-with-clerk'
        }
      ]
    },
    {
      title: '切换企业空间',
      description:
        '点击列表中的企业空间即可切换。选中的空间会成为当前组织上下文，组织相关功能都将使用该空间。',
      links: []
    },
    {
      title: '空间隔离',
      description:
        '每个企业空间独立管理成员、角色、权限和账单，可在同一账号下管理多个团队，并保持数据和设置相互隔离。',
      links: []
    },
    {
      title: '服务端权限检查',
      description:
        '应用按照 Clerk 推荐方式实现多租户身份验证。服务端权限检查确保用户只能访问当前企业空间的资源。',
      links: [
        {
          title: 'Clerk Organizations 文档',
          url: 'https://clerk.com/docs/organizations/overview'
        }
      ]
    }
  ]
};

export const teamInfoContent: InfobarContent = {
  title: '团队管理',
  sections: [
    {
      title: '功能说明',
      description:
        '团队管理页面通过 Clerk OrganizationProfile 组件管理企业空间的成员、角色和安全设置。',
      links: [
        {
          title: 'Clerk Organizations 文档',
          url: 'https://clerk.com/docs/organizations/overview'
        }
      ]
    },
    {
      title: '管理团队成员',
      description: '可以添加、移除和管理团队成员，通过邮箱邀请新成员，并为成员分配角色和访问权限。',
      links: []
    },
    {
      title: '角色和权限',
      description:
        '在 Clerk 控制台的 Organizations 设置中配置默认角色和权限。角色决定成员可以在企业空间内执行的操作。',
      links: [
        {
          title: 'Clerk Organizations 文档',
          url: 'https://clerk.com/docs/organizations/overview'
        }
      ]
    },
    {
      title: '安全设置',
      description: '管理身份验证要求、会话和访问控制等安全设置，保护企业空间的数据和资源。',
      links: []
    },
    {
      title: '组织设置',
      description: '配置组织名称、标志和其他偏好。这些设置应用于整个企业空间及其全部成员。',
      links: []
    },
    {
      title: '导航权限控制',
      description:
        '应用通过 useNav 钩子在客户端过滤导航项，支持 requireOrg、permission 和 role 检查。导航权限在 src/config/nav-config.ts 的 access 属性中配置。',
      links: []
    }
  ]
};

export const billingInfoContent: InfobarContent = {
  title: '账单与套餐',
  sections: [
    {
      title: '功能说明',
      description:
        '账单页面用于管理企业空间的订阅和用量限制。Clerk Billing 为组织级订阅提供管理能力，并集成 Stripe 处理付款。',
      links: [
        {
          title: 'Clerk Billing 文档',
          url: 'https://clerk.com/docs/billing/overview'
        }
      ]
    },
    {
      title: '可选套餐',
      description:
        '通过价格表查看和订阅套餐。套餐在 Clerk 控制台中创建和管理，启用公开可用后会显示在价格表中。',
      links: [
        {
          title: 'Clerk 控制台 - 套餐',
          url: 'https://dashboard.clerk.com/~/billing/plans'
        }
      ]
    },
    {
      title: '套餐功能',
      description:
        '每个套餐可以包含不同功能。功能在 Clerk 控制台中添加，并可在代码中通过 has() 函数检查。',
      links: []
    },
    {
      title: '访问控制',
      description:
        '套餐和功能用于控制应用访问。服务端使用 has() 检查套餐或功能权限，客户端使用 Show 组件根据订阅状态显示内容。',
      links: []
    },
    {
      title: '计费费用',
      description:
        'Clerk Billing 每笔交易收取 0.7% 的费用，Stripe 交易费另计。套餐和定价在 Clerk 控制台中管理，不会与已有 Stripe 产品同步；Stripe 仅用于处理付款。',
      links: []
    },
    {
      title: '启用要求',
      description:
        '请在 Clerk 控制台的 Billing Settings 中启用账单功能。测试时可使用 Clerk 开发网关，生产环境需连接自己的 Stripe 账号；开发环境创建的 Stripe 账号不能用于生产环境。',
      links: [
        {
          title: '账单设置',
          url: 'https://dashboard.clerk.com/~/billing/settings'
        }
      ]
    },
    {
      title: '测试版状态',
      description:
        'Billing 当前仍处于测试阶段，API 可能发生不兼容变更。建议固定 SDK 和 clerk-js 的版本。',
      links: []
    }
  ]
};

export const productInfoContent: InfobarContent = {
  title: '产品管理',
  sections: [
    {
      title: '功能说明',
      description:
        '产品页面用于管理产品目录。列表支持服务端排序、筛选、分页和搜索，点击新增按钮可以创建产品。',
      links: [
        {
          title: '产品管理指南',
          url: '#'
        }
      ]
    },
    {
      title: '新增产品',
      description: '点击页面标题区域的新增按钮，填写产品名称、描述、价格和分类，并可上传产品图片。',
      links: [
        {
          title: '新增产品说明',
          url: '#'
        }
      ]
    },
    {
      title: '编辑产品',
      description: '点击列表中的产品可打开编辑表单。修改产品信息并提交后保存。',
      links: [
        {
          title: '编辑产品指南',
          url: '#'
        }
      ]
    },
    {
      title: '删除产品',
      description: '在产品列表中选择删除操作，确认后产品会从目录中永久移除。',
      links: [
        {
          title: '产品删除说明',
          url: '#'
        }
      ]
    },
    {
      title: '列表功能',
      description: '产品列表支持点击表头排序、按条件筛选、分页浏览和关键词搜索。',
      links: [
        {
          title: '列表功能说明',
          url: '#'
        },
        {
          title: '排序和筛选指南',
          url: '#'
        }
      ]
    },
    {
      title: '产品字段',
      description:
        '产品包含名称（必填）、描述、价格、分类和图片。创建或更新产品时可以编辑这些字段。',
      links: [
        {
          title: '产品字段说明',
          url: '#'
        }
      ]
    }
  ]
};
