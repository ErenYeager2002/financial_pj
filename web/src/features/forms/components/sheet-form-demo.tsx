'use client';

import { useState } from 'react';
import { useAppForm } from '@/lib/form';
import * as z from 'zod';
import { toast } from 'sonner';
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Icons } from '@/components/icons';

// ---------------------------------------------------------------------------
// Schemas
// ---------------------------------------------------------------------------

const sheetFormSchema = z.object({
  name: z.string().min(2, '产品名称至少需要 2 个字符。'),
  category: z.string().min(1, '请选择产品分类。'),
  price: z.number({ error: '请输入价格。' }).min(0.01, '价格必须大于 0。'),
  description: z.string().min(10, '产品描述至少需要 10 个字符。')
});

const dialogFormSchema = z.object({
  rating: z.number().min(0).max(10),
  feedback: z.string().min(5, '反馈内容至少需要 5 个字符。')
});

const categoryOptions = [
  { value: 'beauty', label: '美妆产品' },
  { value: 'electronics', label: '电子产品' },
  { value: 'home', label: '家居园艺' },
  { value: 'sports', label: '户外运动' }
];

// ---------------------------------------------------------------------------
// Sheet Form
// ---------------------------------------------------------------------------

function SheetFormSection() {
  const [open, setOpen] = useState(false);

  const form = useAppForm({
    defaultValues: {
      name: '',
      category: '',
      price: undefined as number | undefined,
      description: ''
    },
    validators: {
      onSubmit: sheetFormSchema
    },
    onSubmit: ({ value }) => {
      toast.success('产品创建成功！', {
        description: `${value.name} 已添加。`
      });
      setOpen(false);
      form.reset();
    }
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>侧边面板表单</CardTitle>
        <CardDescription>
          在侧边面板中创建产品。提交按钮位于表单元素之外，通过 HTML{' '}
          <code className='bg-muted rounded px-1 text-sm'>form</code> 属性与表单关联。
        </CardDescription>
      </CardHeader>
      <CardContent>
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

            <form
              id='sheet-form-id'
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
                      placeholder='0.00'
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
                    />
                  )}
                />
              </FieldGroup>
            </form>

            <SheetFooter className='pt-4'>
              <Button type='button' variant='outline' onClick={() => setOpen(false)}>
                取消
              </Button>
              <Button type='submit' form='sheet-form-id'>
                创建产品
              </Button>
            </SheetFooter>
          </SheetContent>
        </Sheet>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Dialog Form
// ---------------------------------------------------------------------------

function DialogFormSection() {
  const [open, setOpen] = useState(false);

  const form = useAppForm({
    defaultValues: {
      rating: 5,
      feedback: ''
    },
    validators: {
      onSubmit: dialogFormSchema
    },
    onSubmit: ({ value }) => {
      toast.success('反馈已提交！', {
        description: `评分：${value.rating}/10，谢谢！`
      });
      setOpen(false);
      form.reset();
    }
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>对话框表单</CardTitle>
        <CardDescription>在对话框中填写快速反馈，提交按钮位于对话框底部。</CardDescription>
      </CardHeader>
      <CardContent>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger render={<Button variant='outline' />}>
            <Icons.send className='mr-2 h-4 w-4' />
            提交反馈
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>快速反馈</DialogTitle>
              <DialogDescription>请为使用体验评分并填写意见。</DialogDescription>
            </DialogHeader>

            <form
              id='dialog-form-id'
              className='space-y-4 py-2'
              onSubmit={(e) => {
                e.preventDefault();
                form.handleSubmit();
              }}
            >
              <FieldGroup>
                <form.AppField
                  name='rating'
                  children={(field) => (
                    <field.SliderField
                      label='评分'
                      description='请为使用体验评分（0 至 10 分）'
                      min={0}
                      max={10}
                      step={1}
                    />
                  )}
                />

                <form.AppField
                  name='feedback'
                  children={(field) => (
                    <field.TextareaField
                      label='反馈内容'
                      required
                      placeholder='请输入你的意见...'
                      maxLength={300}
                      rows={3}
                    />
                  )}
                />
              </FieldGroup>
            </form>

            <DialogFooter>
              <Button type='button' variant='outline' onClick={() => setOpen(false)}>
                取消
              </Button>
              <Button type='submit' form='dialog-form-id'>
                提交反馈
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Toast Demo
// ---------------------------------------------------------------------------

function ToastDemoSection() {
  return (
    <Card className='md:col-span-2'>
      <CardHeader>
        <CardTitle>消息提示</CardTitle>
        <CardDescription>触发不同类型的消息提示，查看显示效果。</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-wrap gap-2'>
        <Button variant='outline' onClick={() => toast('默认消息提示')}>
          默认
        </Button>
        <Button variant='outline' onClick={() => toast.success('操作成功！')}>
          <Icons.circleCheck className='mr-2 h-4 w-4' />
          成功
        </Button>
        <Button variant='outline' onClick={() => toast.error('操作失败。')}>
          <Icons.circleX className='mr-2 h-4 w-4' />
          错误
        </Button>
        <Button variant='outline' onClick={() => toast.warning('请确认后再继续。')}>
          <Icons.warning className='mr-2 h-4 w-4' />
          警告
        </Button>
        <Button variant='outline' onClick={() => toast.info('这是一条说明信息。')}>
          <Icons.info className='mr-2 h-4 w-4' />
          信息
        </Button>
        <Button
          variant='outline'
          onClick={() =>
            toast.promise(new Promise((resolve) => setTimeout(resolve, 2000)), {
              loading: '正在加载...',
              success: '数据加载完成！',
              error: '数据加载失败。'
            })
          }
        >
          <Icons.spinner className='mr-2 h-4 w-4' />
          异步状态
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main Demo
// ---------------------------------------------------------------------------

export default function SheetFormDemo() {
  return (
    <div className='grid grid-cols-1 gap-6 md:grid-cols-2'>
      <SheetFormSection />
      <DialogFormSection />
      <ToastDemoSection />
    </div>
  );
}
