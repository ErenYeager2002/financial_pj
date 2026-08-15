import * as z from 'zod';

export const userSchema = z.object({
  first_name: z.string().min(1, '请输入名。'),
  last_name: z.string().min(1, '请输入姓。'),
  email: z.string().email('请输入有效的邮箱地址。'),
  phone: z.string().min(1, '请输入手机号。'),
  role: z.string().min(1, '请选择角色。'),
  status: z.string().min(1, '请选择状态。')
});

export type UserFormValues = z.infer<typeof userSchema>;
