import type { Conversation } from './types';

export const initialConversations: Conversation[] = [
  {
    id: 'billing-issue',
    name: '客服 Alex',
    title: '账单问题 #4821',
    status: 'online',
    unread: 2,
    initials: 'AS',
    messages: [
      {
        id: 'billing-1',
        sender: 'contact',
        author: 'Alex',
        text: '你好！系统显示你本月的专业版套餐被重复扣费，我已经为重复款项发起退款。',
        timestamp: '10:02'
      },
      {
        id: 'billing-2',
        sender: 'user',
        author: '你',
        text: '谢谢。退款大概需要多久才能到账？',
        timestamp: '10:05'
      },
      {
        id: 'billing-3',
        sender: 'contact',
        author: 'Alex',
        text: '通常需要 3 至 5 个工作日，具体取决于银行。你应该会在 24 小时内看到一笔待入账退款。还有其他需要协助的吗？',
        timestamp: '10:08'
      }
    ],
    quickReplies: ['好的，谢谢！', '可以提供退款凭证吗？', '我还想咨询套餐升级。'],
    autoReplies: [
      '不客气。针对这次问题，我已为你的下一个账单周期申请 10% 优惠。',
      '可以，退款确认邮件已发送到你的注册邮箱。',
      '当然可以，我来介绍目前可用的套餐。'
    ]
  },
  {
    id: 'api-integration',
    name: '工程师 Priya',
    title: 'API 集成协助',
    status: 'online',
    unread: 0,
    initials: 'PE',
    messages: [
      {
        id: 'api-1',
        sender: 'user',
        author: '你',
        text: '调用 /api/products 接口时出现 429 限流错误，我们每分钟大约只发出 50 个请求。',
        timestamp: '09:15'
      },
      {
        id: 'api-2',
        sender: 'contact',
        author: 'Priya',
        text: '我检查了你的 API 密钥。当前入门版限制为每分钟 30 个请求，增长版支持每分钟 200 个请求。需要升级吗？',
        timestamp: '09:18'
      },
      {
        id: 'api-3',
        sender: 'user',
        author: '你',
        text: '请帮我升级。另外，如何实现遵循 Retry-After 响应头的重试逻辑？',
        timestamp: '09:22'
      },
      {
        id: 'api-4',
        sender: 'contact',
        author: 'Priya',
        text: '在配置中启用 autoRetry: true 后，SDK 会自动处理。我发一段示例代码给你。',
        timestamp: '09:25'
      }
    ],
    quickReplies: ['这会很有帮助。', '也可以发一下限流文档吗？', 'Webhook 接口也出现了超时。'],
    autoReplies: [
      '示例代码已发送，只需在客户端配置中添加 autoRetry: true 和 maxRetries: 3。',
      '限流指南已发送到你的收件箱，其中也介绍了突发请求限制。',
      '我来检查你账号的 Webhook 日志。请提供当前使用的接口地址。'
    ]
  },
  {
    id: 'account-access',
    name: '安全专员 Jordan',
    title: '账号访问请求',
    status: 'offline',
    unread: 1,
    initials: 'JS',
    messages: [
      {
        id: 'access-1',
        sender: 'contact',
        author: 'Jordan',
        text: '我们发现有陌生设备从圣保罗尝试登录。请确认是否为你的操作。出于安全考虑，该会话已被暂时锁定。',
        timestamp: '昨天'
      },
      {
        id: 'access-2',
        sender: 'user',
        author: '你',
        text: '不是我操作的，我在纽约。请撤销该会话，并为我的账号启用双重验证。',
        timestamp: '昨天'
      }
    ],
    quickReplies: ['可以查看所有活跃会话吗？', '也请重置我的密码。', '该会话是否访问过数据？'],
    autoReplies: [
      '除当前会话外，其他会话均已撤销，双重验证也已启用。设置二维码会通过邮件发送。',
      '密码重置链接稍后会发送给你，请设置一个未在其他网站使用过的密码。',
      '该会话在发出任何 API 请求前已被拦截，没有访问数据。'
    ]
  }
];
