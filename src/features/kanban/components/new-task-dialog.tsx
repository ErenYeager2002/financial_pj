'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useTaskStore } from '../utils/store';

export default function NewTaskDialog() {
  const addTask = useTaskStore((state) => state.addTask);
  const [open, setOpen] = useState(false);
  const [titleError, setTitleError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    const form = e.currentTarget;
    if (!form.reportValidity()) return;
    const formData = new FormData(form);
    const { title, description } = Object.fromEntries(formData);

    if (typeof title !== 'string' || typeof description !== 'string') return;
    if (!title.trim()) {
      setTitleError('请输入任务标题。');
      return;
    }
    setTitleError(null);
    addTask(title, description);
    form.reset();
    setOpen(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setTitleError(null);
      }}
    >
      <DialogTrigger render={<Button variant='secondary' size='sm' />}>+ 新增任务</DialogTrigger>
      <DialogContent className='sm:max-w-[425px]'>
        <DialogHeader>
          <DialogTitle>新增任务</DialogTitle>
          <DialogDescription>填写需要完成的任务。</DialogDescription>
        </DialogHeader>
        <form id='task-form' className='grid gap-4 py-4' onSubmit={handleSubmit}>
          <div className='grid grid-cols-4 items-center gap-4'>
            <Input
              id='title'
              name='title'
              placeholder='任务标题...'
              aria-label='任务标题'
              required
              aria-invalid={!!titleError}
              aria-describedby={titleError ? 'task-title-error' : undefined}
              className='col-span-4'
            />
            {titleError && (
              <p id='task-title-error' role='alert' className='text-destructive col-span-4 text-sm'>
                {titleError}
              </p>
            )}
          </div>
          <div className='grid grid-cols-4 items-center gap-4'>
            <Textarea
              id='description'
              name='description'
              placeholder='任务描述（选填）...'
              aria-label='任务描述'
              className='col-span-4'
            />
          </div>
        </form>
        <DialogFooter>
          <Button type='submit' size='sm' form='task-form'>
            添加任务
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
