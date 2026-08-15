'use client';
import { LoadingButton } from '@/components/ui/loading-button';
import { FieldGroup } from '@/components/ui/field';
import { useAppForm } from '@/lib/form';
import { useTransition } from 'react';
import { toast } from 'sonner';
import * as z from 'zod';

const formSchema = z.object({
  email: z.string().email({ message: '请输入有效的邮箱地址。' })
});

export default function UserAuthForm() {
  const [loading, startTransition] = useTransition();

  const form = useAppForm({
    defaultValues: {
      email: ''
    },
    validators: {
      onSubmit: formSchema
    },
    onSubmit: () => {
      startTransition(() => {
        toast.success('登录成功！');
      });
    }
  });

  return (
    <>
      <form
        className='w-full space-y-2'
        onSubmit={(e) => {
          e.preventDefault();
          form.handleSubmit();
        }}
      >
        <FieldGroup>
          <form.AppField
            name='email'
            children={(field) => (
              <field.TextField
                label='邮箱'
                type='email'
                placeholder='请输入邮箱地址...'
                disabled={loading}
              />
            )}
          />
        </FieldGroup>
        <LoadingButton loading={loading} type='submit' className='mt-2 ml-auto w-full'>
          使用邮箱继续
        </LoadingButton>
      </form>
      <div className='relative'>
        <div className='absolute inset-0 flex items-center'>
          <span className='w-full border-t' />
        </div>
        <div className='relative flex justify-center text-xs uppercase'>
          <span className='bg-background text-muted-foreground px-2'>其他登录方式</span>
        </div>
      </div>
    </>
  );
}
