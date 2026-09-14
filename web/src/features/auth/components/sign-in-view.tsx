import { BrandIcon } from '@/components/brand-icon';
import { ThemeModeToggle } from '@/components/themes/theme-mode-toggle';
import { IconArrowRight, IconChecklist, IconFiles, IconLayoutDashboard } from '@tabler/icons-react';
import LocalSignInForm from './local-sign-in-form';

const workspaceAreas = [
  { icon: IconLayoutDashboard, title: '工作台', description: '查看待办，开始日常工作' },
  { icon: IconChecklist, title: '任务中心', description: '跟进执行进度，查阅处理结果' },
  { icon: IconFiles, title: '文件中心', description: '管理业务材料与产出文件' }
];

export default function SignInViewPage() {
  return (
    <div className='flex min-h-svh flex-col bg-background text-foreground'>
      <header className='flex min-h-16 items-center justify-between gap-4 border-b px-5 py-3 sm:px-8'>
        <div className='flex min-w-0 items-center gap-2.5'>
          <BrandIcon className='size-9' />
          <span className='text-sm font-semibold sm:text-base'>财务自动化平台</span>
        </div>
        <ThemeModeToggle />
      </header>
      <main className='flex flex-1 items-center justify-center px-5 py-10 sm:px-8 sm:py-16'>
        <div className='grid w-full max-w-5xl overflow-hidden rounded-2xl border bg-card text-card-foreground md:grid-cols-[1fr_1.05fr]'>
          <section aria-labelledby='workspace-heading' className='flex flex-col border-b bg-sidebar px-6 py-7 text-sidebar-foreground sm:px-10 md:border-r md:border-b-0 md:py-12'>
            <div className='mb-6 flex items-center gap-2 text-xs text-muted-foreground'>
              <span className='h-px w-6 bg-primary' aria-hidden='true' />
              日常财务工作空间
            </div>
            <h2 id='workspace-heading' className='text-2xl leading-snug font-semibold tracking-tight sm:text-3xl'>
              从这里，开始今天的工作。
            </h2>
            <p className='mt-4 max-w-xs text-sm leading-7 text-muted-foreground'>
              业务材料、执行任务与处理结果，<br className='hidden md:block' />在同一个工作空间中管理。
            </p>
            <ul className='mt-10 hidden space-y-6 md:block'>
              {workspaceAreas.map(({ icon: Icon, title, description }) => (
                <li key={title} className='flex items-start gap-3'>
                  <span className='flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background/60'>
                    <Icon className='size-4' aria-hidden='true' />
                  </span>
                  <div>
                    <p className='text-sm font-medium'>{title}</p>
                    <p className='mt-1 text-xs leading-5 text-muted-foreground'>{description}</p>
                  </div>
                </li>
              ))}
            </ul>
            <div className='mt-auto hidden items-center gap-2 pt-12 text-xs text-muted-foreground md:flex'>
              登录后进入工作台 <IconArrowRight className='size-3.5' aria-hidden='true' />
            </div>
          </section>
          <section aria-label='账号登录' className='flex items-center px-6 py-8 sm:px-10 md:px-12 md:py-12'>
            <LocalSignInForm />
          </section>
        </div>
      </main>
      <footer className='px-5 pb-6 text-center text-xs leading-5 text-muted-foreground'>
        财务自动化平台 · 企业内部工作空间
      </footer>
    </div>
  );
}
