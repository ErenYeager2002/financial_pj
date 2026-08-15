'use client';

import * as React from 'react';
import { revalidateLogic, useStore } from '@tanstack/react-form';
import { toast } from 'sonner';
import * as z from 'zod';
import { Icons } from '@/components/icons';
import { FieldDescription, FieldGroup } from '@/components/ui/field';
import { Progress } from '@/components/ui/progress';
import { motion, AnimatePresence } from 'motion/react';
import { useAppForm } from '@/lib/form';
import { useFormStepper } from '@/hooks/use-stepper';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';

// --- Schema ---

const productFormSchema = z.object({
  name: z.string().min(2, '产品名称至少需要 2 个字符。'),
  category: z.string().min(1, '请选择产品分类。'),
  price: z.number({ error: '请输入价格。' }).min(0.01, '价格必须大于 0。'),
  description: z.string().min(10, '产品描述至少需要 10 个字符。')
});

const stepSchemas = [
  // Step 1: Basic Info
  productFormSchema.pick({ name: true, category: true, price: true }),
  // Step 2: Details
  productFormSchema.pick({ description: true }),
  // Step 3: Review (no validation)
  z.object({})
];

const categoryOptions = [
  { value: 'beauty', label: '美妆产品' },
  { value: 'electronics', label: '电子产品' },
  { value: 'home', label: '家居园艺' },
  { value: 'sports', label: '户外运动' }
];

// --- Review summary (reads form values) ---

function ReviewSummary({
  values
}: {
  values: {
    name: string;
    category: string;
    price?: number;
    description: string;
  };
}) {
  return (
    <div className='space-y-3'>
      <Separator />
      <div className='grid gap-3'>
        <div>
          <p className='text-muted-foreground text-xs font-medium uppercase'>名称</p>
          <p className='text-sm'>{values.name || '—'}</p>
        </div>
        <div>
          <p className='text-muted-foreground text-xs font-medium uppercase'>分类</p>
          <p className='text-sm capitalize'>
            {categoryOptions.find((option) => option.value === values.category)?.label || '—'}
          </p>
        </div>
        <div>
          <p className='text-muted-foreground text-xs font-medium uppercase'>价格</p>
          <p className='text-sm'>{values.price != null ? `$${values.price}` : '—'}</p>
        </div>
        <div>
          <p className='text-muted-foreground text-xs font-medium uppercase'>描述</p>
          <p className='text-sm'>{values.description || '—'}</p>
        </div>
      </div>
    </div>
  );
}

// --- Main Form ---

type ProductFormValues = {
  name: string;
  category: string;
  price: number | undefined;
  description: string;
};

export default function MultiStepProductForm() {
  const {
    currentValidator,
    step,
    currentStep,
    isFirstStep,
    handleCancelOrBack,
    handleNextStepOrSubmit
  } = useFormStepper(stepSchemas, { fullSchema: productFormSchema });

  const form = useAppForm({
    defaultValues: {
      name: '',
      category: '',
      price: undefined,
      description: ''
    } as ProductFormValues,
    validationLogic: revalidateLogic(),
    validators: {
      onDynamic: currentValidator as typeof productFormSchema,
      onDynamicAsyncDebounceMs: 500
    },
    onSubmit: () => {
      toast.success('产品创建成功！');
    }
  });

  const isDefault = useStore(form.store, (state) => state.isDefaultValue);
  const formValues = useStore(form.store, (state) => state.values);

  const handleNext = async () => {
    await handleNextStepOrSubmit(form);
  };

  const totalSteps = 3;

  return (
    /* Every submit (Enter key, the review step's submit button) routes
       through the stepper gate — calling form.handleSubmit directly on a
       non-final step would validate only that step's schema and submit. */
    <form
      onSubmit={(e) => {
        e.preventDefault();
        e.stopPropagation();
        void handleNext();
      }}
      noValidate
      className='mx-auto flex w-full flex-col gap-2 p-0'
    >
      <div className='flex flex-col gap-2 pt-3'>
        <div className='flex flex-col items-center justify-start gap-1'>
          <span className='text-muted-foreground text-sm'>
            第 {currentStep} 步，共 {totalSteps} 步
          </span>
          <Progress value={(currentStep / totalSteps) * 100} />
        </div>

        <AnimatePresence mode='popLayout'>
          <motion.div
            key={currentStep}
            initial={{ opacity: 0, x: 15 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -15 }}
            transition={{ duration: 0.4, type: 'spring' }}
            className='flex flex-col gap-2'
          >
            {currentStep === 1 && (
              <FieldGroup className='space-y-4'>
                <h3 className='text-lg font-semibold'>基本信息</h3>
                <FieldDescription>填写产品名称、分类和价格。</FieldDescription>

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
              </FieldGroup>
            )}

            {currentStep === 2 && (
              <FieldGroup className='space-y-4'>
                <h3 className='text-lg font-semibold'>详细信息</h3>
                <FieldDescription>填写产品的详细描述。</FieldDescription>

                <form.AppField
                  name='description'
                  children={(field) => (
                    <field.TextareaField
                      label='产品描述'
                      required
                      placeholder='请输入产品描述'
                      maxLength={500}
                      rows={5}
                    />
                  )}
                />
              </FieldGroup>
            )}

            {currentStep === 3 && (
              <div className='space-y-4'>
                <h3 className='text-lg font-semibold'>确认并提交</h3>
                <FieldDescription>提交前请核对以下信息。</FieldDescription>
                <ReviewSummary values={formValues} />
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        <div className='flex w-full items-center justify-between gap-3 pt-3'>
          <Button
            size='sm'
            variant='ghost'
            type='button'
            disabled={isFirstStep}
            onClick={() => handleCancelOrBack({ onBack: () => {} })}
          >
            <Icons.chevronLeft /> 上一步
          </Button>
          <div className='flex w-full items-center justify-end gap-3 pt-3'>
            {!isDefault && (
              <Button
                type='button'
                onClick={() => form.reset()}
                className='rounded-lg'
                variant='outline'
                size='sm'
              >
                重置
              </Button>
            )}
            {step.isCompleted ? (
              <Button type='submit'>提交</Button>
            ) : (
              <Button size='sm' variant='ghost' type='button' onClick={() => void handleNext()}>
                下一步 <Icons.chevronRight />
              </Button>
            )}
          </div>
        </div>
      </div>
    </form>
  );
}
