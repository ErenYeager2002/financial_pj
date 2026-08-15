import * as z from 'zod';

const MAX_FILE_SIZE = 5_000_000;
const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];

export const productSchema = z.object({
  image: z
    .any()
    .refine((files) => files?.length == 1, '请上传产品图片。')
    .refine((files) => files?.[0]?.size <= MAX_FILE_SIZE, '文件大小不能超过 5 MB。')
    .refine(
      (files) => ACCEPTED_IMAGE_TYPES.includes(files?.[0]?.type),
      '仅支持 .jpg、.jpeg、.png 和 .webp 格式。'
    ),
  name: z.string().min(2, '产品名称至少需要 2 个字符。'),
  category: z.string().min(1, '请选择产品分类。'),
  price: z.number({ message: '请输入价格。' }),
  description: z.string().min(10, '产品描述至少需要 10 个字符。')
});

export type ProductFormValues = {
  image: File[] | undefined;
  name: string;
  category: string;
  price: number | undefined;
  description: string;
};
