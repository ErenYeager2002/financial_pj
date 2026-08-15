'use client';

import { Button } from '@/components/ui/button';
import { LoadingButton } from '@/components/ui/loading-button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldGroup } from '@/components/ui/field';
import { useAppForm } from '@/lib/form';
import { categoryOptions } from '@/features/products/constants/product-options';
import { productSchema, type ProductFormValues } from '@/features/products/schemas/product';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { createProductMutation, updateProductMutation } from '../api/mutations';
import type { Product } from '../api/types';

export default function ProductForm({
  initialData,
  pageTitle
}: {
  initialData: Product | null;
  pageTitle: string;
}) {
  const router = useRouter();
  const isEdit = !!initialData;

  const createMutation = useMutation({
    ...createProductMutation,
    onSuccess: () => {
      toast.success('产品已创建');
      router.push('/dashboard/product');
    },
    onError: () => {
      toast.error('产品创建失败，请重试。');
    }
  });

  const updateMutation = useMutation({
    ...updateProductMutation,
    onSuccess: () => {
      toast.success('产品已更新');
      router.push('/dashboard/product');
    },
    onError: () => {
      toast.error('产品更新失败，请重试。');
    }
  });

  const form = useAppForm({
    defaultValues: {
      image: undefined,
      name: initialData?.name ?? '',
      category: initialData?.category ?? '',
      price: initialData?.price,
      description: initialData?.description ?? ''
    } as ProductFormValues,
    validators: {
      onSubmit: productSchema
    },
    onSubmit: ({ value }) => {
      const payload = {
        name: value.name,
        category: value.category,
        price: value.price!,
        description: value.description
      };

      if (isEdit) {
        updateMutation.mutate({ id: initialData.id, values: payload });
      } else {
        createMutation.mutate(payload);
      }
    }
  });

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Card className='mx-auto w-full max-w-3xl'>
      <CardHeader>
        <CardTitle className='text-left text-2xl font-bold'>{pageTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className='space-y-8'
          onSubmit={(e) => {
            e.preventDefault();
            form.handleSubmit();
          }}
        >
          <FieldGroup>
            <form.AppField
              name='image'
              children={(field) => (
                <field.FileUploadField
                  label='产品图片'
                  description='上传产品图片'
                  maxSize={5 * 1024 * 1024}
                  maxFiles={4}
                />
              )}
            />

            <div className='grid grid-cols-1 gap-6 md:grid-cols-2'>
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
                    step={0.01}
                    placeholder='请输入价格'
                  />
                )}
              />
            </div>

            <form.AppField
              name='description'
              children={(field) => (
                <field.TextareaField
                  label='产品描述'
                  required
                  placeholder='请输入产品描述'
                  maxLength={500}
                  rows={4}
                />
              )}
            />
          </FieldGroup>

          <div className='flex justify-end gap-2'>
            <Button type='button' variant='outline' onClick={() => router.back()}>
              取消
            </Button>
            <LoadingButton loading={isPending} type='submit'>
              {isEdit ? '更新产品' : '新增产品'}
            </LoadingButton>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
