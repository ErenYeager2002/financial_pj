import * as z from 'zod';

export const profileSchema = z.object({
  firstname: z.string().min(2, { message: '名字至少需要 2 个字符。' }),
  lastname: z.string().min(1, { message: '请输入姓氏。' }),
  email: z.string().email({ message: '请输入有效的邮箱地址。' }),
  contactno: z.coerce.number(),
  country: z.string().min(1, { message: '请选择国家或地区。' }),
  city: z.string().min(1, { message: '请选择城市。' }),
  // jobs array is for the dynamic fields
  jobs: z.array(
    z.object({
      jobcountry: z.string().min(1, { message: '请选择工作所在国家或地区。' }),
      jobcity: z.string().min(1, { message: '请选择工作所在城市。' }),
      jobtitle: z.string().min(2, { message: '职位名称至少需要 2 个字符。' }),
      employer: z.string().min(2, { message: '单位名称至少需要 2 个字符。' }),
      startdate: z.string().refine((value) => /^\d{4}-\d{2}-\d{2}$/.test(value), {
        message: '开始日期格式应为 YYYY-MM-DD。'
      }),
      enddate: z.string().refine((value) => /^\d{4}-\d{2}-\d{2}$/.test(value), {
        message: '结束日期格式应为 YYYY-MM-DD。'
      })
    })
  )
});

export type ProfileFormValues = z.infer<typeof profileSchema>;
