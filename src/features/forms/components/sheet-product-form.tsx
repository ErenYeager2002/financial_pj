'use client';

import { useAppForm } from '@/lib/form';
import * as z from 'zod';
import { Button } from '@/components/ui/button';
import { FieldGroup } from '@/components/ui/field';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger
} from '@/components/ui/sheet';
import { Icons } from '@/components/icons';
import { useState } from 'react';

const productSchema = z.object({
  name: z.string().min(2, '产品名称至少需要 2 个字符。'),
  category: z.string().min(1, '请选择产品分类。'),
  price: z.number({ error: '请输入价格。' }).min(0.01, '价格必须大于 0。'),
  description: z.string().min(10, '产品描述至少需要 10 个字符。')
});

const categoryOptions = [
  { value: 'beauty', label: '美妆产品' },
  { value: 'electronics', label: '电子产品' },
  { value: 'home', label: '家居园艺' },
  { value: 'sports', label: '户外运动' }
];

export default function SheetProductForm() {
  const [open, setOpen] = useState(false);

  const form = useAppForm({
    defaultValues: {
      name: '',
      category: '',
      price: undefined as number | undefined,
      description: ''
    },
    validators: {
      onSubmit: productSchema
    },
    onSubmit: () => {
      alert('产品创建成功！');
      setOpen(false);
      form.reset();
    }
  });

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={<Button />}>
        <Icons.add className='mr-2 h-4 w-4' />
        新增产品
      </SheetTrigger>
      <SheetContent className='flex flex-col'>
        <SheetHeader>
          <SheetTitle>新增产品</SheetTitle>
          <SheetDescription>填写以下信息以创建产品。</SheetDescription>
        </SheetHeader>

        <div className='flex-1 overflow-auto'>
          <form
            id='sheet-product-form'
            className='space-y-4 p-4 md:p-4'
            onSubmit={(e) => {
              e.preventDefault();
              form.handleSubmit();
            }}
          >
            <FieldGroup>
              <form.AppField
                name='name'
                children={(field) => (
                  <field.TextField label='产品名称' required placeholder='请输入产品名称' />
                )}
              />

              <form.AppField
                name='category'
                children={(field) => (
                  <field.SelectField
                    label='产品分类'
                    required
                    options={categoryOptions}
                    placeholder='请选择分类'
                  />
                )}
              />

              <form.AppField
                name='price'
                children={(field) => (
                  <field.TextField
                    label='价格'
                    required
                    type='number'
                    min={0}
                    step='0.01'
                    placeholder='请输入价格'
                  />
                )}
              />

              <form.AppField
                name='description'
                children={(field) => (
                  <field.TextareaField
                    label='产品描述'
                    required
                    placeholder='请输入产品描述'
                    maxLength={500}
                    rows={4}
                    showCount
                  />
                )}
              />
            </FieldGroup>
          </form>
        </div>

        <SheetFooter>
          <Button type='button' variant='outline' onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button type='submit' form='sheet-product-form'>
            创建产品
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
