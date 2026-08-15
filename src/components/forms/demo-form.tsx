'use client';

import * as React from 'react';
import { useStore } from '@tanstack/react-form';
import * as z from 'zod';
import { useAppForm } from '@/lib/form';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { FieldGroup } from '@/components/ui/field';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ToggleGroupItem } from '@/components/ui/toggle-group';
import type { DateRange } from 'react-day-picker';
import { Icons } from '@/components/icons';

// Schema — validated on submit, errors display next to each field
const demoFormSchema = z.object({
  name: z.string().min(2, '姓名至少需要 2 个字符。'),
  email: z.email('请输入有效的邮箱地址。'),
  age: z.number({ error: '请输入年龄。' }).min(18, '年龄不能小于 18 岁。'),
  password: z.string().min(8, '密码至少需要 8 个字符。'),
  phone: z.string().min(10, '手机号至少需要 10 位。'),
  website: z.string().url('请输入有效的网址。').or(z.literal('')),
  bio: z.string().min(10, '个人简介至少需要 10 个字符。'),
  country: z.string().min(1, '请选择国家或地区。'),
  framework: z.string().min(1, '请选择开发框架。'),
  interests: z.array(z.string()).min(1, '请至少选择一项兴趣。'),
  gender: z.string().min(1, '请选择性别。'),
  newsletter: z.boolean(),
  rating: z.number().min(0).max(10),
  birthDate: z.date().optional(),
  dateRange: z.any().optional(),
  eventTime: z.string().optional(),
  favoriteColor: z.string().optional(),
  otp: z.string().min(6, '请输入 6 位验证码。'),
  formatting: z.array(z.string()).optional(),
  tags: z.array(z.string()).min(1, '请至少添加一个标签。'),
  terms: z.boolean().refine((val) => val === true, '请先同意条款和条件。'),
  avatar: z.array(z.any()).optional()
});

const countryOptions = [
  { value: 'us', label: '美国' },
  { value: 'ca', label: '加拿大' },
  { value: 'uk', label: '英国' },
  { value: 'au', label: '澳大利亚' },
  { value: 'de', label: '德国' },
  { value: 'fr', label: '法国' }
];

const frameworkOptions = [
  { value: 'next', label: 'Next.js' },
  { value: 'remix', label: 'Remix' },
  { value: 'astro', label: 'Astro' },
  { value: 'nuxt', label: 'Nuxt' },
  { value: 'svelte', label: 'SvelteKit' },
  { value: 'angular', label: 'Angular' }
];

const interestOptions = [
  { value: 'technology', label: '科技' },
  { value: 'sports', label: '运动' },
  { value: 'music', label: '音乐' },
  { value: 'travel', label: '旅行' },
  { value: 'cooking', label: '烹饪' },
  { value: 'reading', label: '阅读' }
];

const genderOptions = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
  { value: 'other', label: '其他' },
  { value: 'prefer-not-to-say', label: '不愿透露' }
];

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className='space-y-1'>
      <Separator />
      <h3 className='text-muted-foreground pt-2 text-sm font-medium tracking-wide uppercase'>
        {children}
      </h3>
    </div>
  );
}

// ─── Form ───

type DemoFormValues = {
  name: string;
  email: string;
  age?: number;
  password: string;
  phone: string;
  website: string;
  bio: string;
  country: string;
  framework: string;
  interests: string[];
  gender: string;
  newsletter: boolean;
  rating: number;
  birthDate?: Date;
  dateRange?: DateRange;
  eventTime?: string;
  favoriteColor?: string;
  otp: string;
  formatting?: string[];
  tags: string[];
  terms: boolean;
  avatar?: File[];
};

export default function DemoForm() {
  const form = useAppForm({
    defaultValues: {
      name: '',
      email: '',
      age: undefined,
      password: '',
      phone: '',
      website: '',
      bio: '',
      country: '',
      framework: '',
      interests: [],
      gender: '',
      newsletter: false,
      rating: 5,
      birthDate: undefined,
      dateRange: undefined,
      eventTime: '',
      favoriteColor: '#6366f1',
      otp: '',
      formatting: [],
      tags: [],
      terms: false,
      avatar: []
    } as DemoFormValues,
    validators: {
      onSubmit: demoFormSchema
    },
    onSubmit: () => {
      alert('表单提交成功！');
    }
  });

  const formValues = useStore(form.store, (s) => s.values);
  const isSubmitting = useStore(form.store, (s) => s.isSubmitting);

  return (
    <div className='grid grid-cols-1 gap-6 xl:grid-cols-[1fr_320px]'>
      <Card>
        <CardHeader>
          <CardTitle className='text-2xl font-bold'>完整表单控件演示</CardTitle>
          <p className='text-muted-foreground'>
            使用 TanStack Form 和 shadcn/ui 构建的常用表单控件
          </p>
        </CardHeader>
        <CardContent>
          <form
            className='space-y-6'
            noValidate
            aria-busy={isSubmitting}
            onSubmit={(e) => {
              e.preventDefault();
              form.handleSubmit();
            }}
          >
            {/* ─── TEXT INPUTS ─── */}
            <SectionTitle>文本输入</SectionTitle>

            <FieldGroup className='grid grid-cols-1 gap-4 md:grid-cols-2'>
              <form.AppField
                name='name'
                children={(field) => (
                  <field.TextField label='姓名' required placeholder='请输入姓名' />
                )}
              />

              {/* Async validation: simulated server-side email check */}
              <form.AppField
                name='email'
                asyncDebounceMs={500}
                validators={{
                  onChangeAsync: async ({ value }) => {
                    if (!value || value.length < 3) return undefined;
                    await new Promise((r) => setTimeout(r, 500));
                    if (value === 'taken@example.com') {
                      return { message: '该邮箱已注册。' };
                    }
                    return undefined;
                  }
                }}
                children={(field) => (
                  <field.TextField
                    label='邮箱'
                    required
                    type='email'
                    placeholder='john@example.com'
                  />
                )}
              />

              <form.AppField
                name='password'
                children={(field) => (
                  <field.TextField
                    label='密码'
                    required
                    type='password'
                    placeholder='至少 8 个字符'
                  />
                )}
              />

              <form.AppField
                name='age'
                children={(field) => (
                  <field.TextField
                    label='年龄'
                    required
                    type='number'
                    min={18}
                    max={100}
                    placeholder='18'
                  />
                )}
              />

              <form.AppField
                name='phone'
                children={(field) => (
                  <field.TextField
                    label='手机号'
                    required
                    type='tel'
                    placeholder='+1 (555) 000-0000'
                  />
                )}
              />

              <form.AppField
                name='website'
                children={(field) => (
                  <field.TextField label='个人网站' type='url' placeholder='https://example.com' />
                )}
              />
            </FieldGroup>

            {/* ─── TEXTAREA ─── */}
            <form.AppField
              name='bio'
              children={(field) => (
                <field.TextareaField
                  label='个人简介'
                  required
                  placeholder='请介绍一下自己...'
                  maxLength={500}
                  rows={4}
                  showCount
                />
              )}
            />

            {/* ─── SELECT & COMBOBOX ─── */}
            <SectionTitle>选择器与搜索选择器</SectionTitle>

            <FieldGroup className='grid grid-cols-1 gap-4 md:grid-cols-2'>
              <form.AppField
                name='country'
                children={(field) => (
                  <field.SelectField
                    label='国家或地区'
                    required
                    options={countryOptions}
                    placeholder='请选择国家或地区'
                  />
                )}
              />

              <form.AppField
                name='framework'
                children={(field) => (
                  <field.ComboboxField
                    label='开发框架'
                    required
                    description='支持搜索的下拉选项'
                    options={frameworkOptions}
                    placeholder='搜索开发框架...'
                  />
                )}
              />
            </FieldGroup>

            {/* ─── CHECKBOX & RADIO ─── */}
            <SectionTitle>复选框与单选框</SectionTitle>

            <form.AppField
              name='interests'
              mode='array'
              children={(field) => (
                <field.CheckboxGroupField
                  label='兴趣爱好'
                  required
                  description='可以选择多项'
                  options={interestOptions}
                  className='grid grid-cols-2 gap-3 md:grid-cols-3'
                />
              )}
            />
            {formValues.interests.length > 0 && (
              <div className='flex flex-wrap gap-2'>
                {formValues.interests.map((v) => (
                  <Badge key={v} variant='secondary'>
                    {interestOptions.find((o) => o.value === v)?.label || v}
                  </Badge>
                ))}
              </div>
            )}

            <form.AppField
              name='gender'
              children={(field) => (
                <field.RadioGroupField label='性别' required options={genderOptions} />
              )}
            />

            {/* ─── TOGGLE & SWITCH ─── */}
            <SectionTitle>按钮组与开关</SectionTitle>

            <form.AppField
              name='newsletter'
              children={(field) => (
                <field.SwitchField label='订阅产品动态' description='接收新功能和产品更新通知' />
              )}
            />

            <form.AppField
              name='formatting'
              mode='array'
              children={(field) => (
                <field.ToggleGroupField label='文本格式' description='可以选择多种格式'>
                  <ToggleGroupItem value='bold' aria-label='粗体'>
                    <Icons.bold className='h-4 w-4' />
                  </ToggleGroupItem>
                  <ToggleGroupItem value='italic' aria-label='斜体'>
                    <Icons.italic className='h-4 w-4' />
                  </ToggleGroupItem>
                  <ToggleGroupItem value='underline' aria-label='下划线'>
                    <Icons.underline className='h-4 w-4' />
                  </ToggleGroupItem>
                </field.ToggleGroupField>
              )}
            />

            <form.AppField
              name='terms'
              children={(field) => <field.CheckboxField label='我同意条款和条件' required />}
            />

            {/* ─── SLIDER ─── */}
            <SectionTitle>滑块</SectionTitle>

            <form.AppField
              name='rating'
              children={(field) => (
                <field.SliderField
                  label='总体评分'
                  description='请为使用体验评分（0 至 10 分）'
                  min={0}
                  max={10}
                  step={0.5}
                />
              )}
            />

            {/* ─── DATE & TIME ─── */}
            <SectionTitle>日期与时间</SectionTitle>

            <FieldGroup className='grid grid-cols-1 gap-4 md:grid-cols-2'>
              <form.AppField
                name='birthDate'
                children={(field) => (
                  <field.DatePickerField
                    label='出生日期'
                    disabledDates={(date) => date > new Date()}
                  />
                )}
              />

              <form.AppField
                name='eventTime'
                children={(field) => <field.TextField label='活动时间' type='time' />}
              />
            </FieldGroup>

            <form.AppField
              name='dateRange'
              children={(field) => <field.DateRangeField label='日期范围' />}
            />

            {/* ─── SPECIAL INPUTS ─── */}
            <SectionTitle>特殊输入控件</SectionTitle>

            <FieldGroup className='grid grid-cols-1 gap-4 md:grid-cols-2'>
              <form.AppField
                name='otp'
                children={(field) => (
                  <field.OtpField label='验证码' required description='请输入 6 位验证码' />
                )}
              />

              <form.AppField
                name='favoriteColor'
                children={(field) => (
                  <field.ColorField label='喜欢的颜色' description='颜色选择器和十六进制颜色值' />
                )}
              />
            </FieldGroup>

            <form.AppField
              name='tags'
              mode='array'
              children={(field) => (
                <field.TagsField
                  label='标签'
                  required
                  description='按回车键或点击添加按钮创建标签'
                />
              )}
            />

            {/* ─── FILE UPLOAD ─── */}
            <SectionTitle>文件上传</SectionTitle>

            <form.AppField
              name='avatar'
              children={(field) => (
                <field.FileUploadField
                  label='头像'
                  description='拖放文件或点击上传，最大 5 MB'
                  maxSize={5000000}
                  maxFiles={1}
                />
              )}
            />

            {/* ─── SUBMIT ─── */}
            <Separator />
            <div className='flex gap-4 pt-2'>
              <Button
                type='button'
                variant='outline'
                onClick={() => form.reset()}
                className='flex-1'
              >
                重置
              </Button>
              <form.AppForm>
                <form.SubmitButton className='flex-1'>提交表单</form.SubmitButton>
              </form.AppForm>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Form Data Preview - sticky sidebar */}
      <div className='xl:sticky xl:top-16 xl:self-start'>
        <Card>
          <CardHeader>
            <CardTitle>表单数据预览</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className='bg-muted max-h-[calc(100vh-8rem)] overflow-auto rounded-lg p-4 text-xs'>
              {JSON.stringify(formValues, null, 2)}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
